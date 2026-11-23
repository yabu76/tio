/*
 * tio - a serial device I/O tool
 *
 * Copyright (c) 2014-2024  Martin Lund
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

#pragma once

#include <stdbool.h>

/*
 * Start monitoring modem input signals.
 * Returns 0 on success, -1 on error.
 */
int serial_signal_start(int fd);

/* Stop the signal monitor thread. Safe to call more than once. */
void serial_signal_stop(void);

/* File descriptor used to wake up the main thread. */
int serial_signal_wakeup_fd(void);

/* Drain pending wake-up notifications. */
void serial_signal_drain_wakeup(void);

/*
 * Get one signal-change event.
 * Returns true if an event was available.
 */
bool serial_signal_get_change(int *current, int *previous);

