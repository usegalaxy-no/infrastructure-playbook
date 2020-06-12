#!/bin/bash
PATH=/srv/galaxy/venv/bin:/usr/local/bin:$PATH gxadmin uwsgi stats-influx 127.0.0.1:4010 2>/dev/null || true
exit 0
