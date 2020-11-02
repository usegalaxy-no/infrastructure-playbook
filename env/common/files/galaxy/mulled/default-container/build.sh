ung#!/bin/bash

singularity build galaxy-python.sif galaxy-python.def

cp galaxy-python.sif /srv/galaxy/containers/galaxy-python.sif

