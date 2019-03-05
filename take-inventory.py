# For each path in folders.txt, run regex terms defined in terms.txt

import csv
import os
import subprocess
import sys
import pathlib
import re
import json

from slugify import slugify
from utilities import get_next_filename, parse_folders_terms_arguments

# Get input file arguments, defaulting to folders.txt and terms.txt
config_file, _ = parse_folders_terms_arguments(sys.argv[1:])

if config_file is None:
    print("Usage: python take-inventory.py --config <config_file>")
    sys.exit(2)

config = None
with open(config_file, 'r') as config_file:
    config = json.load(config_file)

if config is None:
    print("Could not deserialize config file")
    sys.exit(1)

# Compile search terms
for search in config["inventory"]:
    search["terms"] = [re.compile(term, re.IGNORECASE | re.MULTILINE) for term in search["terms"]]

results = {}

for content_set in config["content"]:
    # Each line in folders.txt has a label, a path, and a base URL separated by whitespace.
    # (The "None" arg to split() says "any amount of whitespace is the separator".)
    docset = content_set.get("repo")
    folder = content_set.get("path")
    base_url = content_set.get("url")

    if folder is None:
        print("No path for docset {} - skipping".format(docset))
        continue

    if docset is None or base_url is None:
        print("Malformed config entry for docset {}; check your config file".format(docset))
        continue

    print('take-inventory: Processing ' + docset + ' at ' + folder)

    for root, dirs, files in os.walk(folder):
        for file in files:
            if pathlib.Path(file).suffix != '.md':
                continue
            full_path = os.path.join(root, file)
            try:
                content = pathlib.Path(full_path).read_text()
            except UnicodeDecodeError:
                print("WARNING: File {} contains non-UTF-8 characters: Must be converted. Skipping.".format(full_path))
                continue

            for search in config["inventory"]:
                name = search["name"].lower()
                if name not in results:
                    results[name] = []

                for term in search["terms"]:
                    # Finding the first match is sufficient for inventory purposes - it will likely occur
                    # multiple times in the file.
                    match = term.search(content)
                    if match is not None:
                        line_start = content.rfind("\n", match.span()[0])
                        line_end = content.find("\n", match.span()[1])
                        line = content[0:match.span()[0]].count("\n") + 1
                        url = full_path.replace(folder, base_url).replace('.md','').replace('\\','/')
                        results[name].append([docset, full_path, url, term.pattern, line, content[line_start:line_end]])

# Sort the results (by filename, then line number), because a sorted list is needed for
# consolidate.py, and this removes the need to open the .csv file in Excel for a manual sort.
print("take-inventory: Sorting results by filename")
for inventory, rows in results.iteritems():
    rows.sort(key=lambda row: (row[1], int(row[4])))  # Use int on [4] to sort the line numbers numerically

    # Open CSV output file, which we do before running the searches because
    # we consolidate everything into a single file

    result_filename = get_next_filename(inventory)
    print('take-inventory: Writing CSV results file %s.csv' % (result_filename))

    with open(result_filename + '.csv', 'w', newline='', encoding='utf-8') as csv_file:    
        writer = csv.writer(csv_file)
        writer.writerow(['Docset', 'File', 'URL', 'Term', 'Line', 'Extract'])
        writer.writerows(rows)

    print("take-inventory: Completed first CSV results file")
    print("take-inventory: Invoking secondary processing to extract metadata")

    # Run the other scripts, which can also be run independently 
    subprocess.call('python extract-metadata.py %s.csv' % (result_filename))

    # HACK: assumes knowledge of the extract-metadata.py file naming...
    subprocess.call('python consolidate.py --config=%s %s-metadata.csv' % (config_file, result_filename))
