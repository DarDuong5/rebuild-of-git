import argparse

argparser = argparse.ArgumentParser(description="Hello, welcome to BootGit!")
argsubparsers: argparse.ArgumentParser = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True 

argsp = argsubparsers.add_parser("init", help="Initialize a new, empty repository.")
argsp.add_argument("path", metavar="directory", nargs="?", default=".", help="Where to create the repository.")

argsp = argsubparsers.add_parser("find", help="Finds the root starting from the current directory.")
argsp.add_argument("path", metavar="directory", nargs="?", default=".", help="Where to start searching the repository.")

argsp = argsubparsers.add_parser("cat-file", help="Provide content of repository objects.")
argsp.add_argument("type", metavar="type", choices=["blob", "commit", "tag", "tree"], help="Specify the type.")
argsp.add_argument("object", metavar="object", help="The object to display.")

argsp = argsubparsers.add_parser("hash-object", help="Compute object ID and optionally creates a blob from a file.")
argsp.add_argument("-t", metavar="type", dest="type", choices=["blob", "commit", "tag", "tree"], default="blob", help="Specify the type.")
argsp.add_argument("-w", dest="write", action="store_true", help="Actually write the object into the database.")
argsp.add_argument("path", help="Read objects from <file>.")

argsp = argsubparsers.add_parser("log", help="Display history of a given commit.")
argsp.add_argument("commit", default="HEAD", nargs="?", help="Commit to start at.")

argsp = argsubparsers.add_parser("ls-tree", help="Pretty-print a tree object.")
argsp.add_argument("-r", dest="recursive", action="store_true", help="Recurse into sub-trees.")
argsp.add_argument("tree", help="A tree-ish object.")

argsp = argsubparsers.add_parser("checkout", help="Checkout a commit inside of a directory.")
argsp.add_argument("commit", help="The commit or tree to checkout.")
argsp.add_argument("path", help="The EMPTY directory to checkout on.")

argsp = argsubparsers.add_parser("show-ref", help="List references.")

argsp = argsubparsers.add_parser("tag", help="List and create tags.")
argsp.add_argument("-a", action="store_true", dest="create_tag_object", help="Whether to create a tag object.")
argsp.add_argument("name", nargs="?", help="The new tag's name.")
argsp.add_argument("object", default="HEAD", nargs="?", help="The object the new tag will point to.")

argsp = argsubparsers.add_parser("rev-parse", help="Parse revision (or other objects) indentifiers.")
argsp.add_argument("--bootgit-type", metavar="type", dest="type", choices=["blob", "commit", "tag", "tree"], default=None, help="Specify the expected type.")
argsp.add_argument("name", help="The name to parse.")

argsp = argsubparsers.add_parser("ls-files", help="Displays the names of files in the staging area.")
argsp.add_argument("--verbose", action="store_true", help="Show everything.")

argsp = argsubparsers.add_parser("check-ignore", help="Check path(s) against ignore rules.")
argsp.add_argument("path", nargs="+", help="Paths to check.")

arpsp = argsubparsers.add_parser("status", help="Show the working tree status.")

argsp = argsubparsers.add_parser("rm", help="Remove files from the working tree and the index.")
argsp.add_argument("path", nargs="+", help="Files to remove.")

argsp = argsubparsers.add_parser("add", help="Add file contents to the index.")
argsp.add_argument("path", nargs="+", help="Files to add.")

argsp = argsubparsers.add_parser("commit", help="Records the changes to the repository.")
argsp.add_argument("-m", metavar="message", dest="message", help="Message to associate with this commit.")
