import argparse

# Create ArgumentParser object
parser = argparse.ArgumentParser(description='Convert from fit to gpx.')

# Add arguments
parser.add_argument('arg1', type=str, help='sourcefile.fit')
parser.add_argument('arg2', type=str, help='targetfile.gpx')

# Parse the arguments
args = parser.parse_args()

# Access the arguments
print('arg1:', args.arg1)
print('arg2:', args.arg2)


from fit2gpx import Converter

conv = Converter()

# gpx = conv.fit_to_gpx(f_in='c:/export_55533644/activities/11336529236.fit', f_out='11336529236.gpx')
gpx = conv.fit_to_gpx(f_in=args.arg1, f_out=args.arg2)
