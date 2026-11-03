#!/usr/bin/env python3

#
# python3 e2e_test.py ../build/src/tio [--verbose]
#

from _test_runner import run_tests
from test_read import READ_TESTS
from test_expect import EXPECT_TESTS
from test_hook import HOOK_TESTS
from test_subcmd import SUBCMD_TESTS

def main():
    run_tests(READ_TESTS + EXPECT_TESTS + HOOK_TESTS + SUBCMD_TESTS)

if __name__ == "__main__":
    main()
