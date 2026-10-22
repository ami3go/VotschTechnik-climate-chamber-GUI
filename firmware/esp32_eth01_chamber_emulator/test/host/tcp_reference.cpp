// Linux host transport using the SAME emulator_protocol.cpp as the ESP32.
// Intended only for CI and development on isolated loopback/private networks.
#include "emulator_protocol.h"
#include <arpa/inet.h>
#include <csignal>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#include <array>
#include <string>

static volatile std::sig_atomic_t running = 1;
static void stop(int) { running = 0; }
struct Client { int fd=-1; std::string request; };
int main(int argc, char **argv) {
    bool drop_stop = argc > 1 && std::string(argv[1]) == "--drop-stop-reply";
    std::signal(SIGTERM, stop);
    std::signal(SIGINT, stop);
    int listener = ::socket(AF_INET, SOCK_STREAM, 0);
    if (listener < 0) return 2;
    int yes = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(emu::PROTOCOL_PORT);
    addr.sin_addr.s_addr = INADDR_ANY;
    if (bind(listener, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) || listen(listener, 8)) {
        std::perror("bind/listen"); close(listener); return 3;
    }
    std::array<Client,4> clients{};
    emu::Chamber model;
    emu::Faults faults;
    std::cout << "REFERENCE TCP 2049 READY" << std::endl;
    while (running) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(listener,&readfds);
        int maxfd=listener;
        for (auto &c: clients) if(c.fd >= 0) {FD_SET(c.fd,&readfds); if(c.fd>maxfd) maxfd=c.fd;}
        timeval tv{0,100000};
        int count=select(maxfd+1,&readfds,nullptr,nullptr,&tv);
        if (count < 0) { if (errno==EINTR) continue; break; }
        if (FD_ISSET(listener,&readfds)) {
            int fd=accept(listener,nullptr,nullptr);
            if(fd>=0) {
                bool attached=false;
                for(auto &c: clients) if(c.fd<0) {c.fd=fd; c.request.clear(); attached=true; break;}
                if(!attached) close(fd);
            }
        }
        for(auto &c:clients) if(c.fd>=0 && FD_ISSET(c.fd,&readfds)) {
            char b[64];
            ssize_t n=recv(c.fd,b,sizeof(b),0);
            if(n<=0) {close(c.fd);c.fd=-1;c.request.clear();continue;}
            for(ssize_t i=0;i<n && c.fd>=0;++i) {
                if(c.request.size()>=emu::MAX_FRAME) {
                    close(c.fd);c.fd=-1;c.request.clear();break;
                }
                c.request.push_back(b[i]);
                if(b[i]=='\r') {
                    const bool is_stop = c.request == std::string("14001") + char(0xB6) + "1" + char(0xB6) + "1" + char(0xB6) + "0\r";
                    auto response=emu::handle_frame(c.request,model,faults);
                    if(drop_stop && is_stop) { close(c.fd);c.fd=-1; }
                    else if (send(c.fd,response.data(),response.size(),MSG_NOSIGNAL)!=ssize_t(response.size())) {
                        close(c.fd);c.fd=-1;
                    }
                    c.request.clear();
                }
            }
        }
    }
    for(auto &c:clients) if(c.fd>=0) close(c.fd);
    close(listener);
}
