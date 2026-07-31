# SCADA test process Makefile.
# Kept inside the narrow variable model the makefile_resolver understands:
#   SRCS, INCLUDE (-I tokens), LIBS, simple $(VAR) expansion.

SRCS = src/main.c \
       src/dio_layer.c \
       src/scan_proc.c \
       src/alarm_proc.c \
       src/hist_proc.c \
       src/macro_flow.c \
       src/edge_cases.c

INCLUDE = -Iheaders

LIBS = lib/scf_stubs.c

all:
	@echo "SCADA test process (analysis target, not a real build)"
