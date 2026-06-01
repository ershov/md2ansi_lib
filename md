#!/bin/bash
LINE_WIDTH=150 md2ansi_lib.py "$@" | less -RS
