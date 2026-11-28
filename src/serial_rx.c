/*
 * tio - a serial device I/O tool
 *
 * Copyright (c) 2014-2022  Martin Lund
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

/*
 * Serial receive thread and shared receive ring buffer.
 */

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <sys/select.h>
#include <sys/time.h>
#include <time.h>
#include <termios.h>
#include <unistd.h>

#include "serial_rx.h"

extern unsigned long rx_total, rx_buffer_overflow, rx_buffer_max_consumption;

#define SERIAL_RX_BUFFER_SIZE_DEFAULT (1U * 1024U * 1024U)
#define SERIAL_RX_CHUNK_SIZE 4096

#define READ_END 0
#define WRITE_END 1

static unsigned char *rx_buffer_data;
static size_t rx_buffer_size = SERIAL_RX_BUFFER_SIZE_DEFAULT;
static size_t rx_buffer_head;
static size_t rx_bufer_len;
static int serial_fd = -1;
static int wake_pipe[2] = {-1, -1};
static int stop_pipe[2] = {-1, -1};
static pthread_t rx_thread;
static pthread_mutex_t rx_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t rx_cond = PTHREAD_COND_INITIALIZER;
static bool rx_running;
static bool rx_stopping;
static int rx_error;

static void notify_main(void)
{
    const unsigned char byte = 1;
    if (wake_pipe[WRITE_END] >= 0)
        (void)write(wake_pipe[WRITE_END], &byte, sizeof(byte));
}

static void *serial_rx_worker(void *unused)
{
    unsigned char chunk_buf[SERIAL_RX_CHUNK_SIZE];
    (void)unused;

    for (;;)
    {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(serial_fd, &readfds);
        FD_SET(stop_pipe[READ_END], &readfds);
        int maxfd = (serial_fd > stop_pipe[READ_END]) ? serial_fd : stop_pipe[READ_END];

        pthread_mutex_lock(&rx_mutex);
        if (rx_bufer_len == rx_buffer_size)
            rx_buffer_overflow++;
        while (!rx_stopping && rx_bufer_len == rx_buffer_size)
            pthread_cond_wait(&rx_cond, &rx_mutex);
        bool stopping = rx_stopping;
        size_t available = rx_buffer_size - rx_bufer_len;
        pthread_mutex_unlock(&rx_mutex);
        if (stopping)
            break;

        struct timeval tv = {0, 200 * 1000};
        int selected = select(maxfd + 1, &readfds, NULL, NULL, &tv);
        if (selected < 0)
        {
            if (errno == EINTR)
                continue;
            pthread_mutex_lock(&rx_mutex);
            rx_error = errno;
            pthread_cond_broadcast(&rx_cond);
            pthread_mutex_unlock(&rx_mutex);
            notify_main();
            break;
        }
        if (selected == 0)
            continue;
        if (FD_ISSET(stop_pipe[READ_END], &readfds))
            break;
        if (!FD_ISSET(serial_fd, &readfds))
            continue;

        size_t amount = (available < sizeof(chunk_buf)) ? available : sizeof(chunk_buf);
        if (amount == 0)
        {
            continue;
        }
        ssize_t count = read(serial_fd, chunk_buf, amount);
        if (count < 0)
        {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
                continue;
            pthread_mutex_lock(&rx_mutex);
            rx_error = errno;
            pthread_cond_broadcast(&rx_cond);
            pthread_mutex_unlock(&rx_mutex);
            notify_main();
            break;
        }
        if (count == 0)
        {
            pthread_mutex_lock(&rx_mutex);
            rx_error = EIO;
            pthread_cond_broadcast(&rx_cond);
            pthread_mutex_unlock(&rx_mutex);
            notify_main();
            break;
        }

        pthread_mutex_lock(&rx_mutex);
        rx_total += (unsigned long)count;
        size_t tail = (rx_buffer_head + rx_bufer_len) % rx_buffer_size;
        size_t first = rx_buffer_size - tail;
        if (first > (size_t)count)
            first = (size_t)count;
        memcpy(rx_buffer_data + tail, chunk_buf, first);
        if ((size_t)count > first)
            memcpy(rx_buffer_data, chunk_buf + first, (size_t)count - first);
        rx_bufer_len += (size_t)count;
        if (rx_buffer_max_consumption < rx_bufer_len)
            rx_buffer_max_consumption = rx_bufer_len;
        pthread_cond_broadcast(&rx_cond);
        pthread_mutex_unlock(&rx_mutex);
        notify_main();
    }

    return NULL;
}

/*
 * Consumer-side function
 */

static int make_nonblocking_pipe(int fds[2])
{
    if (pipe(fds) < 0)
        return -1;
    for (int i = 0; i < 2; i++)
    {
        int flags = fcntl(fds[i], F_GETFL, 0);
        if (flags < 0 || fcntl(fds[i], F_SETFL, flags | O_NONBLOCK) < 0)
        {
            int saved_errno = errno;
            close(fds[0]);
            close(fds[1]);
            fds[0] = fds[1] = -1;
            errno = saved_errno;
            return -1;
        }
        (void)fcntl(fds[i], F_SETFD, FD_CLOEXEC);
    }
    return 0;
}

int serial_rx_start(int fd, size_t buffer_size)
{
    if (rx_running)
    {
        errno = EALREADY;
        return -1;
    }
    if (buffer_size == 0)
    {
        errno = EINVAL;
        return -1;
    }
    rx_buffer_data = malloc(buffer_size);
    if (rx_buffer_data == NULL)
    {
        errno = ENOMEM;
        return -1;
    }
    rx_buffer_size = buffer_size;

    if (make_nonblocking_pipe(wake_pipe) < 0)
    {
        free(rx_buffer_data);
        rx_buffer_data = NULL;
        rx_buffer_size = SERIAL_RX_BUFFER_SIZE_DEFAULT;
        return -1;
    }
    if (make_nonblocking_pipe(stop_pipe) < 0)
    {
        close(wake_pipe[READ_END]);
        close(wake_pipe[WRITE_END]);
        wake_pipe[READ_END] = -1;
        wake_pipe[WRITE_END] = -1;
        free(rx_buffer_data);
        rx_buffer_data = NULL;
        rx_buffer_size = SERIAL_RX_BUFFER_SIZE_DEFAULT;
        return -1;
    }

    pthread_mutex_lock(&rx_mutex);
    serial_fd = fd;
    rx_buffer_head = 0;
    rx_bufer_len = 0;
    rx_error = 0;
    rx_stopping = false;
    pthread_mutex_unlock(&rx_mutex);

    int rc = pthread_create(&rx_thread, NULL, serial_rx_worker, NULL);
    if (rc != 0)
    {
        close(wake_pipe[READ_END]);
        close(wake_pipe[WRITE_END]);
        close(stop_pipe[READ_END]);
        close(stop_pipe[WRITE_END]);
        wake_pipe[READ_END] = -1;
        wake_pipe[WRITE_END] = -1;
        stop_pipe[READ_END] = -1;
        stop_pipe[WRITE_END] = -1;
        serial_fd = -1;
        free(rx_buffer_data);
        rx_buffer_data = NULL;
        rx_buffer_size = SERIAL_RX_BUFFER_SIZE_DEFAULT;
        errno = rc;
        return -1;
    }
    rx_running = true;
    return 0;
}

void serial_rx_stop(void)
{
    if (!rx_running)
        return;

    /*
     * serial_rx_ wakeup_fd() brings wake_pipe[READ_END] to main thread.
     * so wake_pipe[READ_END] is not closed here.
     */
    pthread_mutex_lock(&rx_mutex);
    rx_stopping = true;
    pthread_cond_broadcast(&rx_cond);
    pthread_mutex_unlock(&rx_mutex);

    const unsigned char byte = 1;
    (void)write(stop_pipe[WRITE_END], &byte, sizeof(byte));
    pthread_join(rx_thread, NULL);
    rx_running = false;
    close(wake_pipe[WRITE_END]);
    close(stop_pipe[READ_END]);
    close(stop_pipe[WRITE_END]);
    wake_pipe[WRITE_END] = -1;
    stop_pipe[READ_END] = -1;
    stop_pipe[WRITE_END] = -1;

    pthread_mutex_lock(&rx_mutex);
    serial_fd = -1;
    rx_buffer_head = 0;
    rx_bufer_len = 0;
    rx_error = 0;
    rx_stopping = false;
    pthread_mutex_unlock(&rx_mutex);

    free(rx_buffer_data);
    rx_buffer_data = NULL;
    rx_buffer_size = SERIAL_RX_BUFFER_SIZE_DEFAULT;
}

static int wait_for_data_locked(int timeout)
{
    int rc = 0;
    if (timeout == 0)
        return rx_bufer_len ? 1 : (rx_error ? -1 : 0);
    if (timeout < 0)
    {
        while (rx_bufer_len == 0 && rx_error == 0 && !rx_stopping)
        {
            rc = pthread_cond_wait(&rx_cond, &rx_mutex);
            if (rc != 0)
            {
                errno = rc;
                return -1;
            }
        }
    }
    else
    {
        struct timeval now;
        gettimeofday(&now, NULL);
        struct timespec deadline = {
            .tv_sec = now.tv_sec + timeout / 1000,
            .tv_nsec = now.tv_usec * 1000 + (long)(timeout % 1000) * 1000000L
        };
        if (deadline.tv_nsec >= 1000000000L)
        {
            deadline.tv_sec++;
            deadline.tv_nsec -= 1000000000L;
        }
        while (rx_bufer_len == 0 && rx_error == 0 && !rx_stopping)
        {
            rc = pthread_cond_timedwait(&rx_cond, &rx_mutex, &deadline);
            if (rc == ETIMEDOUT)
                return 0;
            if (rc != 0)
            {
                errno = rc;
                return -1;
            }
        }
    }
    if (rx_bufer_len)
        return 1;
    if (rx_error)
    {
        errno = rx_error;
        return -1;
    }
    return 0;
}

int serial_rx_wait_readable(int fd, int timeout)
{
    (void)fd;
    pthread_mutex_lock(&rx_mutex);
    int rc = wait_for_data_locked(timeout);
    pthread_mutex_unlock(&rx_mutex);
    return rc;
}

ssize_t serial_rx_read(int fd, void *buffer, size_t length, int timeout)
{
    (void)fd;
    if (length == 0)
        return 0;

    pthread_mutex_lock(&rx_mutex);
    int ready = wait_for_data_locked(timeout);
    if (ready <= 0)
    {
        pthread_mutex_unlock(&rx_mutex);
        return ready;
    }
    size_t amount = (rx_bufer_len < length) ? rx_bufer_len : length;
    size_t first = rx_buffer_size - rx_buffer_head;
    if (first > amount)
        first = amount;
    memcpy(buffer, rx_buffer_data + rx_buffer_head, first);
    if (amount > first)
        memcpy((unsigned char *)buffer + first, rx_buffer_data, amount - first);
    rx_buffer_head = (rx_buffer_head + amount) % rx_buffer_size;
    rx_bufer_len -= amount;
    bool pending = (rx_bufer_len != 0) || (rx_error != 0);
    pthread_cond_broadcast(&rx_cond);
    pthread_mutex_unlock(&rx_mutex);

    if (pending)
        notify_main();
    return (ssize_t)amount;
}

int serial_rx_wakeup_fd(void)
{
    return wake_pipe[READ_END];
}

void serial_rx_drain_wakeup(void)
{
    unsigned char buffer[128];
    if (wake_pipe[READ_END] < 0)
        return;
    while (read(wake_pipe[READ_END], buffer, sizeof(buffer)) > 0) {}
}

int serial_rx_flush(int fd, int selector)
{
    int rc = tcflush(fd, selector);
    int saved_errno = errno;
    pthread_mutex_lock(&rx_mutex);
    rx_buffer_head = 0;
    rx_bufer_len = 0;
    pthread_cond_broadcast(&rx_cond);
    pthread_mutex_unlock(&rx_mutex);
    if (rc < 0)
        errno = saved_errno;
    return rc;
}

unsigned long serial_rx_total(void)
{
    pthread_mutex_lock(&rx_mutex);
    unsigned long total = rx_total;
    pthread_mutex_unlock(&rx_mutex);
    return total;
}

unsigned long serial_rx_buffer_overflow(void)
{
    pthread_mutex_lock(&rx_mutex);
    unsigned long ovf = rx_buffer_overflow;
    pthread_mutex_unlock(&rx_mutex);
    return ovf;
}

unsigned long serial_rx_buffer_max_consumption(void)
{
    pthread_mutex_lock(&rx_mutex);
    unsigned long max_cons = rx_buffer_max_consumption;
    pthread_mutex_unlock(&rx_mutex);
    return max_cons;
}
