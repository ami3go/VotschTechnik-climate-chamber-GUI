// Host-native TCP reference for unmodified vendor driver. Identical command core to AVR.
// Binds TCP 2049 to loopback or test interfaces; never contacts hardware.
#include "leonardo_core.h"
#include <arpa/inet.h>
#include <chrono>
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

static volatile std::sig_atomic_t running=1;
static void stop(int) { running=0; }
struct Client { int fd=-1; std::string input; };
int main(int argc,char** argv) {
    const bool lost_stop=(argc>1 && std::string(argv[1])=="--drop-stop-reply");
    std::signal(SIGTERM,stop); std::signal(SIGINT,stop);
    int listener=::socket(AF_INET,SOCK_STREAM,0);
    if(listener<0) return 2;
    int yes=1; setsockopt(listener,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
    sockaddr_in address{};
    address.sin_family=AF_INET; address.sin_port=htons(leonardo::CHAMBER_PORT);
    address.sin_addr.s_addr=INADDR_ANY;
    if(bind(listener,reinterpret_cast<sockaddr*>(&address),sizeof(address)) ||
       listen(listener,8)) {std::perror("bind/listen");close(listener);return 3;}
    std::array<Client,4> clients{};
    leonardo::Chamber chamber;
    leonardo::Faults faults;
    auto prior=std::chrono::steady_clock::now();
    std::cout<<"LEONARDO REFERENCE TCP 2049 READY"<<std::endl;
    while(running) {
        auto now=std::chrono::steady_clock::now();
        auto dt=std::chrono::duration_cast<std::chrono::milliseconds>(now-prior).count();
        if(dt>0) {chamber.advance(static_cast<uint32_t>(dt),faults);prior=now;}
        fd_set readfds; FD_ZERO(&readfds); FD_SET(listener,&readfds);
        int maxfd=listener;
        for(auto& c:clients) if(c.fd>=0) {FD_SET(c.fd,&readfds);if(c.fd>maxfd)maxfd=c.fd;}
        timeval tv{0,50000};
        int rc=select(maxfd+1,&readfds,0,0,&tv);
        if(rc<0) {if(errno==EINTR)continue;break;}
        if(FD_ISSET(listener,&readfds)) {
            int fd=accept(listener,0,0);
            if(fd>=0) {
                bool assigned=false;
                for(auto& c:clients)if(c.fd<0){c.fd=fd;c.input.clear();assigned=true;break;}
                if(!assigned)close(fd);
            }
        }
        for(auto& c:clients)if(c.fd>=0 && FD_ISSET(c.fd,&readfds)) {
            char bytes[64]; ssize_t n=recv(c.fd,bytes,sizeof(bytes),0);
            if(n<=0) {close(c.fd);c.fd=-1;c.input.clear();continue;}
            for(ssize_t i=0;i<n && c.fd>=0;++i) {
                if(c.input.size()>=leonardo::MAX_REQUEST) {
                    close(c.fd);c.fd=-1;c.input.clear();break;
                }
                c.input.push_back(bytes[i]);
                if(bytes[i]=='\r') {
                    uint8_t result[leonardo::MAX_RESPONSE]{};
                    const bool is_stop=leonardo::is_stop_frame(
                        reinterpret_cast<const uint8_t*>(c.input.data()),c.input.size());
                    const size_t count=leonardo::handle_frame(
                        reinterpret_cast<const uint8_t*>(c.input.data()),c.input.size(),
                        chamber,faults,result,sizeof(result));
                    if(lost_stop && is_stop) {close(c.fd);c.fd=-1;}
                    else if(!count || send(c.fd,result,count,MSG_NOSIGNAL)!=ssize_t(count)){
                        close(c.fd);c.fd=-1;
                    }
                    c.input.clear();
                }
            }
        }
    }
    for(auto& c:clients)if(c.fd>=0)close(c.fd);
    close(listener);
}
