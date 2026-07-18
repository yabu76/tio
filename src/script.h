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

#include <sys/time.h>

typedef enum
{
    SCRIPT_RUN_ONCE,
    SCRIPT_RUN_ALWAYS,
    SCRIPT_RUN_NEVER,
    SCRIPT_RUN_END,
} script_run_t;

typedef enum
{
    SCRIPT_HOOK_OK,
    SCRIPT_HOOK_ERROR,
    SCRIPT_HOOK_DROP,
} script_hook_result_t;

typedef enum
{
    SCRIPT_HOOK_ID_IO_RECEIVE = 0,
    SCRIPT_HOOK_ID_IO_SEND,
    SCRIPT_HOOK_ID_LOCAL_RECEIVE,
    SCRIPT_HOOK_ID_LOCAL_SEND,
    SCRIPT_HOOK_ID_SOCKET_RECEIVE,
    SCRIPT_HOOK_ID_SOCKET_SEND,
    SCRIPT_HOOK_ID_SIGNAL_CHANGE,
    SCRIPT_HOOK_ID_TIMER_EXPIRE,
    SCRIPT_HOOK_ID_NUM
} script_hook_id_t;

typedef struct {
    int ref;
    char *buffer;
    size_t buffer_size;
} script_hook_t;

void script_interp_init(void);
void script_device_bind(int fd);
void script_device_unbind(void);
void script_run(const char *script_filename);
void script_run_as_specified_by_options(void);
void script_do_line(const char *script_line);

bool script_hook_enabled(script_hook_id_t hook_id);
void script_hook_cleanup(script_hook_id_t hook_id);

script_hook_result_t script_hook_filter(script_hook_id_t hook_id,
                                        const char *data, size_t length,
                                        const char **filtered_data, size_t *filtered_length);
script_hook_result_t script_hook_signal_change(script_hook_id_t hook_id, int lstat_now, int lstat_before);
script_hook_result_t script_hook_timer_expire(script_hook_id_t hook_id, unsigned long elpased_ms);

const char *script_run_state_to_string(script_run_t state);
