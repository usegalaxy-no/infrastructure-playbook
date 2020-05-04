#!/usr/bin/env python3

import argparse
import sys
import pprint as pp
import gzip
import re

def open_outstream( outfile:str=None, compress:bool=False) -> int:
    fh = sys.stdout

    if outfile is not None:
        if compress:
            fh = gzip.open(outfile, 'wt')
        else:
            fh = open(outfile, 'w')

    return fh



def process_logfile(infile:str, mask:bool=False, outfile:str=None, compress:bool=False) -> None:

    out_fh = open_outstream(outfile, compress)
    print(infile)

    in_fh = open(infile, 'r')


    for line in in_fh:
        if re.search(r'uwsgi: \d+\.\d+\.\d+\.\d+', line) or re.search(r'uwsgi: \[pid:.* \d+\.\d+\.\d+\.\d+ ', line):
            if mask:
                line = re.sub( r' \d+\.\d+\.\d+\.\d+ ', 'XXX.XXX.XXX.XXX', line)
                out_fh.write( line )
        else:
            out_fh.write( line )





def main():
    parser = argparse.ArgumentParser(description='ehosd: the ehos daemon to be run on the master node ')

    parser.add_argument('-o', '--outfile', default=None, help="file to write to, default stdout")
    parser.add_argument('-c', '--compress', default=False, action='store_true',  help="compress output when writing to an outfile")
    parser.add_argument('-m', '--mask', default=False, action='store_true',  help="mask rather than strip IP")
    parser.add_argument('infile', metavar='infiles', nargs=1, help="infile to mask uwsgi IP's in")



    args = parser.parse_args()
    args.infile = args.infile[0]
    pp.pprint( args )

    process_logfile( args.infile, args.mask, args.outfile, args.compress)


if __name__ == "__main__":
    main()
