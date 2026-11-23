/*
 * tio - a serial device I/O tool
 *
 * Copyright (c) 2014-2022  Martin Lund
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 */

/*
 * Serial modem signal monitor thread.
 */

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <termios.h>
#include <unistd.h>

#include "serial_signal.h"

#define SIGNAL_POLL_INTERVAL_MS 10
#define SIGNAL_EVENT_QUEUE_SIZE 256

#define READ_END 0
#define WRITE_END 1

typedef struct
{
    int current;
    int previous;
} signal_event_t;

static int serial_fd = -1;
static int wake_pipe[2] = {-1, -1};
static int stop_pipe[2] = {-1, -1};

static pthread_t signal_thread;
static pthread_mutex_t signal_mutex = PTHREAD_MUTEX_INITIALIZER;

static bool signal_running;
static bool signal_stopping;

static signal_event_t event_queue[SIGNAL_EVENT_QUEUE_SIZE];
static size_t event_head;
static size_t event_count;

static const int SIGNAL_INPUT_MASK = TIOCM_CTS | TIOCM_DSR | TIOCM_CD | TIOCM_RI;

static void notify_main(void)
{
    const unsigned char byte = 1;

    if (wake_pipe[WRITE_END] >= 0)
        (void)write(wake_pipe[WRITE_END], &byte, sizeof(byte));
}

static void enqueue_event(int current, int previous)
{
    pthread_mutex_lock(&signal_mutex);

    if (event_count == SIGNAL_EVENT_QUEUE_SIZE)
    {
        /* Drop the oldest event when the queue is full. */
        event_head = (event_head + 1) % SIGNAL_EVENT_QUEUE_SIZE;
        event_count--;
    }

    size_t tail = (event_head + event_count) % SIGNAL_EVENT_QUEUE_SIZE;

    event_queue[tail].current = current;
    event_queue[tail].previous = previous;
    event_count++;

    pthread_mutex_unlock(&signal_mutex);

    notify_main();
}

static void *serial_signal_worker(void *unused)
{
    (void)unused;

    int previous = -1;

    for (;;)
    {
        int current;

        if (ioctl(serial_fd, TIOCMGET, &current) < 0)
        {
            /*
             * The device may have been disconnected or the driver
             * may no longer support modem-status queries.
             */
            break;
        }

        if ((current & SIGNAL_INPUT_MASK) != (previous & SIGNAL_INPUT_MASK))
        {
            enqueue_event(current, previous);
        }

        previous = current;

        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(stop_pipe[READ_END], &readfds);

        struct timeval tv = {
            .tv_sec = 0,
            .tv_usec = SIGNAL_POLL_INTERVAL_MS * 1000
        };

        int selected = select(stop_pipe[READ_END] + 1, &readfds, NULL, NULL, &tv);
        if (selected < 0)
        {
            if (errno == EINTR)
                continue;
            break;
        }

        if ((selected > 0) && FD_ISSET(stop_pipe[READ_END], &readfds))
        {
            break;
        }
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
        if ((flags < 0) || fcntl(fds[i], F_SETFL, flags | O_NONBLOCK) < 0)
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

int serial_signal_start(int fd)
{
    if (signal_running)
    {
        errno = EALREADY;
        return -1;
    }

    /*
     * Check modem-status support before creating the thread.
     */
    int current;
    if (ioctl(fd, TIOCMGET, &current) < 0)
        return -1;

    if (make_nonblocking_pipe(wake_pipe) < 0)
        return -1;

    if (make_nonblocking_pipe(stop_pipe) < 0)
    {
        close(wake_pipe[READ_END]);
        close(wake_pipe[WRITE_END]);
        wake_pipe[READ_END] = -1;
        wake_pipe[WRITE_END] = -1;
        return -1;
    }

    pthread_mutex_lock(&signal_mutex);
    serial_fd = fd;
    event_head = 0;
    event_count = 0;
    signal_stopping = false;
    pthread_mutex_unlock(&signal_mutex);

    int rc = pthread_create(&signal_thread, NULL, serial_signal_worker, NULL);
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
        errno = rc;
        return -1;
    }

    signal_running = true;
    return 0;
}

void serial_signal_stop(void)
{
    if (!signal_running)
        return;

    /*
     * serial_signal_ wakeup_fd() takes wake_pipe[READ_END] to main thread.
     * so wake_pipe[READ_END] is not closed here.
     */
    pthread_mutex_lock(&signal_mutex);
    signal_stopping = true;
    pthread_mutex_unlock(&signal_mutex);

    const unsigned char byte = 1;
    (void)write(stop_pipe[WRITE_END], &byte, sizeof(byte));

    pthread_join(signal_thread, NULL);
    signal_running = false;

    close(wake_pipe[WRITE_END]);
    close(stop_pipe[READ_END]);
    close(stop_pipe[WRITE_END]);

    wake_pipe[WRITE_END] = -1;
    stop_pipe[READ_END] = -1;
    stop_pipe[WRITE_END] = -1;

    pthread_mutex_lock(&signal_mutex);
    serial_fd = -1;
    event_head = 0;
    event_count = 0;
    signal_stopping = false;
    pthread_mutex_unlock(&signal_mutex);
}

int serial_signal_wakeup_fd(void)
{
    return wake_pipe[READ_END];
}

void serial_signal_drain_wakeup(void)
{
    unsigned char buffer[128];

    if (wake_pipe[READ_END] < 0)
        return;

    while (read(wake_pipe[READ_END], buffer, sizeof(buffer)) > 0) {}
}

bool serial_signal_get_change(int *current, int *previous)
{
    bool available = false;

    pthread_mutex_lock(&signal_mutex);

    if (event_count > 0)
    {
        *current = event_queue[event_head].current;
        *previous = event_queue[event_head].previous;

        event_head = (event_head + 1) % SIGNAL_EVENT_QUEUE_SIZE;
        event_count--;

        available = true;
    }

    pthread_mutex_unlock(&signal_mutex);

    return available;
}
