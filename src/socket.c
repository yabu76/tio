/*
 * tio - a serial device I/O tool
 *
 * Copyright (c) 2014-2022  Martin Lund
 * Copyright (c) 2022  Google LLC
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
 * 02110-1301, USA.
 */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <unistd.h>
#include <string.h>

#include "socket.h"
#include "options.h"
#include "print.h"
#include "tty.h"

#define MAX_SOCKET_CLIENTS 16
#define SOCKET_PORT_DEFAULT 3333

static int sockfd;
static int clientfds[MAX_SOCKET_CLIENTS];
static int socket_family = AF_UNSPEC;
static int port_number = SOCKET_PORT_DEFAULT;
static char socket_read_buffer[BUFSIZ];
static char socket_read_edit_buffer[BUFSIZ * 2 * MAX_SOCKET_CLIENTS];
static size_t socket_read_buffer_length = 0;
static size_t socket_read_edit_buffer_length = 0;

static const char *socket_filename(void)
{
    /* skip 'unix:' */
    return option.socket + 5;
}

static int socket_inet_port(void)
{
    /* skip 'inet:' */
    int port = atoi(option.socket + 5);
    if (port == 0)
    {
        port = SOCKET_PORT_DEFAULT;
    }
    return port;
}

static int socket_inet6_port(void)
{
    /* skip 'inet6:' */
    int port = atoi(option.socket + 6);
    if (port == 0)
    {
        port = SOCKET_PORT_DEFAULT;
    }
    return port;
}

static void socket_exit(void)
{
    if (socket_family == AF_UNIX)
    {
        unlink(socket_filename());
    }
}

static bool socket_stale(const char *path)
{
    struct sockaddr_un addr;
    bool stale = false;
    int sfd;

    /* Test if socket file exists */
    if (access(path, F_OK) == 0)
    {
        /* Create test socket  */
        sfd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (sfd < 0)
        {
            tio_warning_printf("Failure opening socket (%s)", strerror(errno));
            return false;
        }

        /* Prepare address */
        addr.sun_family = AF_UNIX;
        strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

        /* Perform connect to test if socket is active */
        if (connect(sfd, (struct sockaddr *) &addr, sizeof(struct sockaddr_un)) == -1)
        {
            if (errno == ECONNREFUSED)
            {
                // No one is listening on socket file
                stale = true;
            }
        }

        /* Cleanup */
        close(sfd);
    }

    return stale;
}

void socket_configure(void)
{
    struct sockaddr_un sockaddr_unix = {};
    struct sockaddr_in sockaddr_inet = {};
    struct sockaddr_in6 sockaddr_inet6 = {};
    struct sockaddr *sockaddr_p;
    socklen_t socklen;
    int optval = 1;

    /* Parse socket string */

    if (strncmp(option.socket, "unix:", 5) == 0)
    {
        socket_family = AF_UNIX;

        if (strlen(socket_filename()) == 0)
        {
            tio_error_printf("Missing socket filename");
            exit(EXIT_FAILURE);
        }

        if (strlen(socket_filename()) > sizeof(sockaddr_unix.sun_path) - 1)
        {
            tio_error_printf("Socket file path %s too long", option.socket);
            exit(EXIT_FAILURE);
        }
    }

    if (strncmp(option.socket, "inet:", 5) == 0)
    {
        socket_family = AF_INET;

        port_number = socket_inet_port();

        if (port_number < 0)
        {
            tio_error_printf("Invalid port number: %d", port_number);
            exit(EXIT_FAILURE);
        }
    }

    if (strncmp(option.socket, "inet6:", 6) == 0)
    {
        socket_family = AF_INET6;

        port_number = socket_inet6_port();

        if (port_number < 0)
        {
            tio_error_printf("Invalid port number: %d", port_number);
            exit(EXIT_FAILURE);
        }
    }

    if (socket_family == AF_UNSPEC)
    {
        tio_error_printf("%s: Invalid socket scheme, must be prefixed with 'unix:', 'inet:', or 'inet6:'", option.socket);
        exit(EXIT_FAILURE);
    }

    /* Configure socket */

    switch (socket_family)
    {
        case AF_UNIX:
            sockaddr_unix.sun_family = AF_UNIX;
            strncpy(sockaddr_unix.sun_path, socket_filename(), sizeof(sockaddr_unix.sun_path) - 1);
            sockaddr_p = (struct sockaddr *) &sockaddr_unix;
            socklen = sizeof(sockaddr_unix);

            /* Test for stale unix socket file */
            if (socket_stale(socket_filename()))
            {
                tio_printf("Cleaning up old socket file");
                unlink(socket_filename());
            }

            break;

        case AF_INET:
            sockaddr_inet.sin_family = AF_INET;
            sockaddr_inet.sin_addr.s_addr = INADDR_ANY;
            sockaddr_inet.sin_port = htons(port_number);
            sockaddr_p = (struct sockaddr *) &sockaddr_inet;
            socklen = sizeof(sockaddr_inet);
            break;

        case AF_INET6:
            sockaddr_inet6.sin6_family = AF_INET6;
            sockaddr_inet6.sin6_addr = in6addr_any;
            sockaddr_inet6.sin6_port = htons(port_number);
            sockaddr_p = (struct sockaddr *) &sockaddr_inet6;
            socklen = sizeof(sockaddr_inet6);
            break;

        default:
            tio_error_printf("Invalid socket family (%d)", socket_family);
            exit(EXIT_FAILURE);
            break;
    }

    /* Create socket */
    sockfd = socket(socket_family, SOCK_STREAM, 0);
    if (sockfd < 0)
    {
        tio_error_printf("Failed to create socket (%s)", strerror(errno));
        exit(EXIT_FAILURE);
    }

    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, &optval, sizeof(optval)))
    {
        tio_error_printf("Failed to set socket options (%s)", strerror(errno));
        exit(EXIT_FAILURE);
    }

#if defined(SO_NOSIGPIPE) && !defined(MSG_NOSIGNAL)
    if (setsockopt(sockfd, SOL_SOCKET, SO_NOSIGPIPE, &optval, sizeof(optval)))
    {
        tio_error_printf("Failed to set socket options (%s)", strerror(errno));
        exit(EXIT_FAILURE);
    }
#endif

    /* Bind */
    if (bind(sockfd, sockaddr_p, socklen) < 0)
    {
        tio_error_printf("Failed to bind to socket (%s)", strerror(errno));
        exit(EXIT_FAILURE);
    }

    /* Listen */
    if (listen(sockfd, MAX_SOCKET_CLIENTS) < 0)
    {
        tio_error_printf("Failed to listen on socket (%s)", strerror(errno));
        exit(EXIT_FAILURE);
    }

    memset(clientfds, -1, sizeof(clientfds));
    atexit(socket_exit);

    if (socket_family == AF_UNIX)
    {
        tio_printf("Listening on socket %s", socket_filename());
    }
    else
    {
        tio_printf("Listening on socket port %d", port_number);
    }
}

void socket_write(char input_char)
{
    if (!option.socket)
    {
        return;
    }

    /* script hook on socket send */
    const char *sotx_buffer = &input_char;
    size_t sotx_buffer_length = sizeof(input_char);
    script_hook_id_t hook_id = SCRIPT_HOOK_ID_SOCKET_SEND;

    if (script_hook_enabled(hook_id))
    {
        script_hook_result_t hook_result = script_hook_filter(hook_id,
                                                              &input_char,
                                                              sizeof(input_char),
                                                              &sotx_buffer,
                                                              &sotx_buffer_length);
        if (hook_result == SCRIPT_HOOK_DROP)
        {
            tio_error_printf("Dropped hook due to fatal error");
            return;
        }
    }
    if (sotx_buffer_length == 0)
    {
        return;
    }

    for (int i = 0; i != MAX_SOCKET_CLIENTS; ++i)
    {
        if (clientfds[i] != -1)
        {
            ssize_t sent = 0;
            for (size_t total_sent = 0; total_sent < sotx_buffer_length; total_sent += sent)
            {

#if defined(SO_NOSIGPIPE) && !defined(MSG_NOSIGNAL)
                sent = send(clientfds[i], &sotx_buffer[total_sent], sotx_buffer_length - total_sent, 0);
#else
                sent = send(clientfds[i], &sotx_buffer[total_sent], sotx_buffer_length - total_sent, MSG_NOSIGNAL);
#endif
                if (sent <= 0)
                {
                    tio_error_printf_silent("Failed to write to socket (%s)", strerror(errno));
                    close(clientfds[i]);
                    clientfds[i] = -1;
                    break;
                }
            }
        }
    }
}

int socket_add_fds(fd_set *rdfs, bool connected)
{
    if (!option.socket)
    {
        return 0;
    }

    int numclients = 0, maxfd = 0;
    for (int i = 0; i != MAX_SOCKET_CLIENTS; ++i)
    {
        if (clientfds[i] != -1)
        {
            /* let clients block if they try to send while we're disconnected */
            if (connected)
            {
                FD_SET(clientfds[i], rdfs);
                maxfd = MAX(maxfd, clientfds[i]);
            }
            numclients++;
        }
    }
    /* don't bother to accept clients if we're already full */
    if (numclients != MAX_SOCKET_CLIENTS)
    {
        FD_SET(sockfd, rdfs);
        maxfd = MAX(maxfd, sockfd);
    }
    return maxfd;
}

bool socket_handle_input(fd_set *rdfs, const char **output_buffer, size_t *output_buffer_length)
{
    if (!option.socket)
    {
        return false;
    }

    if (FD_ISSET(sockfd, rdfs))
    {
        int clientfd = accept(sockfd, NULL, NULL);
        /* this loop should always succeed because we don't select on sockfd when full */
        for (int i = 0; i != MAX_SOCKET_CLIENTS; ++i)
        {
            if (clientfds[i] == -1)
            {
                clientfds[i] = clientfd;
                break;
            }
        }
    }

    char *edit_char = socket_read_edit_buffer;
    socket_read_edit_buffer_length = 0;

    for (int i = 0; i != MAX_SOCKET_CLIENTS; ++i)
    {
        if (clientfds[i] != -1 && FD_ISSET(clientfds[i], rdfs))
        {
            int status = read(clientfds[i], socket_read_buffer, sizeof(socket_read_buffer));
            if (status == 0)
            {
                close(clientfds[i]);
                clientfds[i] = -1;
                continue;
            }
            if (status < 0)
            {
                tio_error_printf_silent("Failed to read from socket (%s)", strerror(errno));
                close(clientfds[i]);
                clientfds[i] = -1;
                continue;
            }
            socket_read_buffer_length = status;
        }

        /* IMAP for socket read */
        for (size_t j = 0; j < socket_read_buffer_length; j++)
        {
            char ch = socket_read_buffer[j];

            if (socket_read_edit_buffer_length > sizeof(socket_read_edit_buffer)) {
                tio_error_printf("Overflow in socket read edit buffer");
                exit(EXIT_FAILURE);
            }

            /* If INLCR is set, a received NL character shall be translated into a CR character */
            if (ch == '\n' && option.map_i_nl_cr)
            {
                *edit_char++ = '\r';
                socket_read_edit_buffer_length++;
            }
            else if (ch == '\r')
            {
                /* If IGNCR is set, a received CR character shall be ignored (not read). */
                if (option.map_ign_cr)
                {
                    continue;
                }

                /* If IGNCR is not set and ICRNL is set, a received CR character shall be translated into an NL character. */
                if (option.map_i_cr_nl)
                {
                    *edit_char++ = '\n';
                    socket_read_edit_buffer_length++;
                }
            }
            else
            {
                *edit_char++ = ch;
                socket_read_edit_buffer_length++;
            }
        }
    }

    /* script hook on socket receive */
    const char *sorx_buffer = socket_read_edit_buffer;
    size_t sorx_buffer_length = socket_read_edit_buffer_length;
    script_hook_id_t hook_id = SCRIPT_HOOK_ID_SOCKET_RECEIVE;

    if (script_hook_enabled(hook_id))
    {
        script_hook_result_t hook_result = script_hook_filter(hook_id,
                                                              socket_read_edit_buffer,
                                                              socket_read_edit_buffer_length,
                                                              &sorx_buffer,
                                                              &sorx_buffer_length);
        if (hook_result == SCRIPT_HOOK_DROP)
        {
            tio_error_printf("Dropped hook due to fatal error");
            sorx_buffer = socket_read_edit_buffer;
            sorx_buffer_length = 0;
        }
    }

    *output_buffer = sorx_buffer;
    *output_buffer_length = sorx_buffer_length;

    return sorx_buffer_length > 0;
}
