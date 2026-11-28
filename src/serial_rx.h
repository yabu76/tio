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

#pragma once

#include <stddef.h>
#include <sys/types.h>

int serial_rx_start(int fd, size_t buffer_size);
void serial_rx_stop(void);
ssize_t serial_rx_read(int fd, void *buffer, size_t length, int timeout);
int serial_rx_wait_readable(int fd, int timeout);
int serial_rx_wakeup_fd(void);
void serial_rx_drain_wakeup(void);
int serial_rx_flush(int fd, int selector);
unsigned long serial_rx_total(void);
unsigned long serial_rx_buffer_full(void);
unsigned long serial_rx_buffer_max_consumption(void);
