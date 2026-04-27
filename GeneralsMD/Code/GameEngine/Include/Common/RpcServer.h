#pragma once

#include <string>

class JsonTcpRpcServer
{
public:
    explicit JsonTcpRpcServer(unsigned short port = 4500);
    ~JsonTcpRpcServer();

    void ProcessRequests();

private:
    struct Impl;
    Impl *m_impl;
};

extern JsonTcpRpcServer *gRpcServer;
