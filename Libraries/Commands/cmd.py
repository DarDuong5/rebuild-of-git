import configparser
import grp
from os import stat_result
from posixpath import abspath
import pwd
import sys
from typing import TYPE_CHECKING, BinaryIO, Optional
from venv import create
from blinker import Namespace
import re
from datetime import datetime

from Objects.Trees.TreeLeafs.git_tree_leaf import GitTreeLeaf
from StageIndex.IndexEntry.git_index_entry import GitIndexEntry
from Libraries.Arguments.args import *
from GitRepo.git_repository import GitRepository
from Objects.Trees.git_tree import GitTree
from Objects.object_func import *
from Refs.ref_func import *
from Objects.Tags.git_tag import GitTag
from StageIndex.stage_index_func import index_read, index_write
from GitIgnore.git_ignore_func import check_ignored_absolute, check_ignored_scoped, gitignore_read
from GitIgnore.Ignore.git_ignore import GitIgnore

if TYPE_CHECKING:
    from Objects.git_object import GitObject
    from StageIndex.GitIndex.git_index import GitIndex

DictRefs = dict[str, Union[str, 'DictRefs']]


# ------------------------------------------------[init]--------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    repo = GitRepository.repo_create(args.path)
    print(f"Initialized empty Git repository in {repo.gitdir}")

def find(args: argparse.Namespace) -> None:
    try:
        repo: 'GitRepository' = GitRepository.repo_find(args.path)
        print(f"Git repository found at: {repo.worktree}")
    except Exception as e:
        print(f"Error: {e}")

# ------------------------------------------------[cat-file]--------------------------------------------------

def cmd_cat_file(args: argparse.Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    cat_file(repo, args.object, object_type=args.type.encode())

def cat_file(repo: 'GitRepository', obj: str, object_type: Optional[bytes] = None) -> None:
    obj = object_read(repo, object_find(repo, obj, object_type=object_type))
    sys.stdout.buffer.write(obj.serialize())

def object_find(repo: 'GitRepository', name: str, object_type: 'GitObject' = None, follow: bool = True) -> str:
    sha: list[str] = object_resolve(repo, name)
    if not sha:
        raise Exception(f"No such reference {name}.")
    if len(sha) > 1:
        candidates = '\n - '.join(sha)
        raise Exception(f"Ambiguous reference {name}: Candidates are: \n - {candidates}.")
    
    sha: str = sha[0]

    if not object_type:
        return sha
    
    while True:
        obj: 'GitObject' = object_read(repo, sha)
        if obj.object_type == object_type:
            return sha
        
        if not follow:
            return None
        
        if obj.object_type == b'tag':
            sha = obj.kvlm[b'object'].decode("ascii")
        elif obj.object_type == b'commit' and object_type == b'tree':
            sha = obj.kvlm[b'tree'].decode("ascii")
        else:
            return None


# # ------------------------------------------------[hash-object]--------------------------------------------------

def cmd_hash_object(args: argparse.Namespace) -> None:
    if args.write:
        repo: 'GitRepository' = GitRepository.repo_find()
    else:
        repo = None

    with open(args.path, "rb") as file_desc:
        sha = object_hash(file_desc, args.type.encode(), repo)
        print(sha)

def object_hash(file_desc: BinaryIO, object_type: bytes, repo: 'GitRepository' = None) -> str:
    data: bytes = file_desc.read()

    match object_type:
        case b'commit': obj=GitCommit(data)
        case b'tree': obj=GitTree(data)
        case b'tag': obj=GitTag(data)
        case b'blob': obj=GitBlob(data)
        case _: raise Exception(f"Unknown type {object_type}!")

    return object_write(obj, repo)

# ------------------------------------------------[log]--------------------------------------------------

def cmd_log(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    print("digraph wyaglog{")
    print("  node[shape=rect]")
    log_graphviz(repo, object_find(repo, args.commit), set())
    print("}")

def log_graphviz(repo: 'GitRepository', sha: str, seen: set) -> None:
    if sha in seen:
        return
    seen.add(sha)

    commit = object_read(repo, sha)
    message = commit.kvlm[None].decode("utf8").strip()
    message = message.replace("\\", "\\\\")
    message = message.replace("\"", "\\\"")

    if "\n" in message:
        message = message[:message.index("\n")]

    print(f"  c_{sha} [label=\"{sha[0:7]}: {message}\"]")
    assert commit.object_type == b"commit"

    if not b'parent' in commit.kvlm.keys():
        return
    
    parents = commit.kvlm[b'parent']

    if type(parents) != list:
        parents = [parents]

    for p in parents:
        p = p.decode("ascii")
        print(f"  c_{sha} -> c_{p};")
        log_graphviz(repo, p, seen)

# ------------------------------------------------[ls-tree]--------------------------------------------------

def cmd_ls_tree(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    ls_tree(repo, args.tree, args.recursive)

def ls_tree(repo: 'GitRepository', ref, recursive=None, prefix="") -> None:
    sha: str = object_find(repo, ref, object_type=b"tree")
    obj: Optional['GitObject'] = object_read(repo, sha)
    for item in obj.items:
        if len(item.mode) == 5:
            type = item.mode[0:1]
        else:
            type = item.mode[0:2]
    
        match type:
            case b'04': type = "tree"
            case b'10': type = "blob" #regular file
            case b'12': type = "blob" #symlink; blob contents is link target
            case b'16': type = "commit" #submodule
            case _: raise Exception(f"Weird tree leaf mode: {item.mode}")

        if not (recursive and type == 'tree'):
            print(f"{'0'*(6-len(item.mode)) + item.mode.decode('ascii')} {type} {item.sha}\t{os.path.join(prefix, item.path)}")
        else:
            ls_tree(repo, item.sha, recursive, os.path.join(prefix, item.path))

# ------------------------------------------------[checkout]--------------------------------------------------

def cmd_checkout(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()

    obj: Optional['GitObject'] = object_read(repo, object_find(repo, args.commit))

    if obj.object_type == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))
    
    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception(f"Not a directory {args.path}!")
        if os.listdir(args.path):
            raise Exception(f"Not empty {args.path}!")
    else:
        os.makedirs(args.path)

    tree_checkout(repo, obj, os.path.realpath(args.path))

def tree_checkout(repo: 'GitRepository', tree, path: str) -> None:
    for item in tree.items:
        obj: Optional['GitObject'] = object_read(repo, item.sha)
        dest: str = os.path.join(path, item.path)

        if obj.object_type == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.object_type == b'blob':
            with open(dest, 'wb') as f:
                f.write(obj.blobdata)

# ------------------------------------------------[show-ref]--------------------------------------------------

def cmd_show_ref(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix="refs")

def show_ref(repo: 'GitRepository', refs: dict, with_hash: bool = True, prefix: str = "refs") -> None:
    if prefix:
        prefix += "/"
    for k, v in refs.items():
        if type(v) == str and with_hash:
            print(f"{v} {prefix}{k}")
        elif type(v) == str:
            print(f"{prefix}{k}")
        else:
            show_ref(repo, v, with_hash=with_hash, prefix=f"{prefix}{k}")

# ------------------------------------------------[tag]--------------------------------------------------

def cmd_tag(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()

    if args.name:
        tag_create(repo, args.name, args.object, create_tag_object=args.create_tag_object)
    else:
        refs = ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)

def tag_create(repo: 'GitRepository', name: str, ref: str, create_tag_object: bool = False) -> None:
    sha: str = object_find(repo, ref)

    if create_tag_object:
        tag: 'GitTag' = GitTag()
        tag.kvlm = dict()
        tag.kvlm[b"object"] = sha.encode()
        tag.kvlm[b"type"] = b"commit"
        tag.kvlm[b"tag"] = name.encode()
        tag.kvlm[b"tagger"] = b"BootGit <BootGit@example.com"
        tag.kvlm[None] = b"A tag generated by BootGit, which won't let you customize the message!\n"
        tag_sha: str = object_write(tag, repo)
        ref_create(repo, "tags/" + name, tag_sha)
    else:
        ref_create(repo, "tags/" + name, sha)

def ref_create(repo: 'GitRepository', ref_name: str, sha: str) -> None:
    filename: str = GitRepository.repo_file(repo, "refs/" + ref_name)
    with open(filename, "w") as f:
        f.write(sha + "\n")

# ------------------------------------------------[rev-parse]--------------------------------------------------

def object_resolve(repo: 'GitRepository', name: str) -> list[str]:
    candidates: list[str] = []
    hashRE: re = re.compile(r"^[0-9A-Fa-f]{4,40}$")

    if not name.strip():
        return None
    
    if name == "HEAD":
        return [ref_resolve(repo, "HEAD")]
    
    if hashRE.match(name):
        name = name.lower()
        prefix: str = name[0:2]
        path: Optional[str] = GitRepository.repo_dir(repo, "objects", prefix, mkdir=False)
        if path:
            remaining: str = name[2:]
            for file in os.listdir(path):
                if file.startswith(remaining):
                    candidates.append(prefix + file)

    as_tag: str = ref_resolve(repo, "ref/tags/" + name)
    if as_tag:
        candidates.append(as_tag)

    as_branch: str = ref_resolve(repo, "ref/heads/" + name)
    if as_branch:
        candidates.append(as_branch)

    as_remote_branch: str = ref_resolve(repo, "ref/remotes/" + name)
    if as_remote_branch:
        candidates.append(as_remote_branch)

    return candidates

def cmd_rev_parse(args: Namespace) -> None:
    if args.type:
        object_type: bytes = args.type.encode()
    else:
        object_type = None

    repo: 'GitRepository' = GitRepository.repo_find()

    print(object_find(repo, args.name, object_type, follow=True))

# ------------------------------------------------[ls-files]--------------------------------------------------

def cmd_ls_files(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    index: 'GitIndex' = index_read(repo)
    if args.verbose:
        print(f"Index file format v{index.version}, containing {len(index.entries)} entries.")
    
    for e in index.entries:
        print(e.name)
        if args.verbose:
            entry_type = {0b1000: "regular file",
                        0b1010: "symlink",
                        0b1110: "git link"}[e.mode_type]
            print(f"\t{entry_type} with perms: {e.mode_perms:o}")
            print(f"\ton blob: {e.sha}")

            created: datetime = datetime.fromtimestamp(e.ctime[0])
            modified: datetime = datetime.fromtimestamp(e.mtime[0])
            print(f"\tcreated: {created}.{e.ctime[1]:09d}, modified: {modified}.{e.mtime[1]:09d}")

            print(f"\tdevice: {e.dev}, inode: {e.ino}")
            print(f"\tuser: {pwd.getpwuid(e.uid).pw_name} ({e.uid}), group: {grp.getgrgid(e.gid).gr_name} ({e.gid})")
            print(f"\tflags: stage={e.flag_stage} assume_valid={e.flag_assume_valid}")

# ------------------------------------------------[check-ignore]--------------------------------------------------

def cmd_check_ignore(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    rules = gitignore_read(repo)
    for path in args.path:
        if check_ignore(rules, path):
            print(path)

def check_ignore(rules: 'GitIgnore', path: str) -> Optional[bool]:
    if os.path.isabs(path):
        raise Exception("This function requires path to be relative to the repository's root.")
    
    result: Optional[bool] = check_ignored_scoped(rules.scoped, path)
    if result != None:
        return result
    
    return check_ignored_absolute(rules.absolute, path)

# ------------------------------------------------[status]--------------------------------------------------

def cmd_status(_) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    index: 'GitIndex' = index_read(repo)

    cmd_status_branch(repo)
    cmd_status_head_index(repo, index)
    print()
    cmd_status_index_work_tree(repo, index)

def branch_get_active(repo: 'GitRepository') -> Union[bool, str]:
    with open(GitRepository.repo_file(repo, "HEAD"), "r") as f:
        head = f.read()

    if head.startswith("ref: ref/heads/"):
        return head[16:-1]
    else:
        return False
    
def cmd_status_branch(repo: 'GitRepository') -> None:
    branch = branch_get_active(repo)
    if branch:
        print(f"On branch {branch}.")
    else:
        print(f"HEAD detached at {object_find(repo, 'HEAD')}")

def tree_to_dict(repo: 'GitRepository', ref: str, prefix: str = "") -> dict:
    ret: dict = dict()
    tree_sha: str = object_find(repo, ref, object_type=b'tree')
    tree: Optional[GitObject] = object_read(repo, tree_sha)

    for leaf in tree.items:
        full_path: str = os.path.join(prefix, leaf.path)

        is_subtree: bool = leaf.mode.startswith(b'04')

        if is_subtree:
            ret.update(tree_to_dict(repo, leaf.sha, full_path))
        else:
            ret[full_path] = leaf.sha

    return ret

# Signature: GitRepository, GitIndex -> None
# Purpose: Compares the HEAD tree with the index (staging area) to see what changes are staged for commit.
def cmd_status_head_index(repo: 'GitRepository', index: 'GitIndex') -> None:
    print("Changes to be commmited:")

    head = tree_to_dict(repo, "HEAD")
    for entry in index.entries:
        if entry in head:
            if head[entry.name] != entry.sha:
                print(f"\t modified {entry.name}")
            del head[entry.name]
        else:
            print(f"\t added {entry.name}")

    for item in head.keys():
        print(f"\t removed {item}")

# Signature: GitRepository, GitIndex -> None 
# Purpose: Compares the index (staging area) with the working directory to see what changes are not yet staged for commit.
#          Identifies untracked (new) files not in the index.
def cmd_status_index_work_tree(repo: 'GitRepository', index: 'GitIndex') -> None:
    print("Changes not staged for commit:")

    ignore: 'GitIgnore' = gitignore_read(repo)
    
    gitdir_prefix: str = repo.gitdir + os.path.sep

    all_files: list[str] = []

    for (root, _, files) in os.walk(repo.worktree, True):
        if root == repo.gitdir or root.startswith(gitdir_prefix):
            continue
        for f in files:
            full_path: str = os.path.join(root, f)
            rel_path: str = os.path.relpath(full_path, repo.worktree)
            all_files.append(rel_path)

    for entry in index.entries:
        full_path: str = os.path.join(repo.worktree, entry.name)

        if not os.path.exists(full_path):
            print(f"\t deleted {entry.name}")
        else:
            stat: stat_result = os.stat(full_path)

            ctime_ns = entry.ctime[0] * 10**9 + entry.ctime[1]
            mtime_ns = entry.mtime[0] * 10**9 + entry.mtime[1]
            if (stat.st_ctime_ns != ctime_ns) or (stat.st_mtime_ns != mtime_ns):
                with open(full_path, "rb") as fd:
                    new_sha = object_hash(fd, b'blob', None)
                    same = entry.sha == new_sha
                if not same:
                    print(f"\t modified {entry.name}")

        if entry.name in all_files:
            all_files.remove(entry.name)

    print()
    print("Untracked files:")

    for f in all_files:
        if not check_ignore(ignore, f):
            print(f"\t{f}")
        
# ------------------------------------------------[rm]--------------------------------------------------

# Signature: Namespace -> None
# Purpose: Extracts the argument from the CLI and delegates to the rm function.
def cmd_rm(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    rm(repo, args.path)

# Signature: GitRepository, list[str], bool, bool -> None
# Purpose: Gets the a repo and a list of paths, reads that repo index and removes entries that matches that list of paths.
def rm(repo: 'GitRepository', paths: list[str], delete: bool = True, skip_missing: bool = False) -> None:
    index: 'GitIndex' = index_read(repo)
    worktree: str = repo.worktree + os.sep
    absolute_paths: set = {}
    
    for path in paths:
        absolute_path: str = os.path.abspath(path)
        if absolute_path.startswith(worktree):
            absolute_paths.add(path)
        else:
            raise Exception("Cannot remove paths outside of the worktree.")
    
    kept_entries: list = []
    removed_entries: list = []

    for e in index.entries:
        full_path: str = os.path.join(repo.worktree, e.name)
        if full_path in absolute_paths:
            removed_entries.append(full_path)
            absolute_paths.remove(full_path)
        else:
            kept_entries.append(e)
    
    if len(absolute_paths) > 0 and not skip_missing:
        raise Exception(f"Cannot remove paths not in the index: {absolute_paths}")
    
    if delete:
        for path in removed_entries:
            os.unlink(path)

    index.entries = kept_entries
    index_write(repo, index)

# ------------------------------------------------[add]--------------------------------------------------

# Signature: Namespace -> None
# Purpose: Extracts the argument from the CLI and delegates to the add function.
def cmd_add(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    add(repo, args.path)

# Signature: GitRepository, list[str], bool, bool -> None
# Purpose: Removes the existing index entry (if there's one) and modifies it with the add changes and writes it back.
def add(repo: 'GitRepository', paths: list[str], delete: bool = True, skip_missing: bool = False) -> None:
    rm(repo, paths, delete=False, skip_missing=True)
    
    worktree: str = repo.worktree + os.sep

    clean_paths: set = {}
    for path in paths:
        absolute_path: str = os.path.abspath(path)
        if not (absolute_path.startswith(worktree) and os.path.isfile(absolute_path)):
            raise Exception(f"Not a file, or outside the worktree: {paths}")
        relative_path: str = os.path.relpath(absolute_path, repo.worktree)
        clean_paths.add((absolute_path, relative_path))

    index: 'GitIndex' = index_read(repo)

    for (abspath, relpath) in clean_paths:
        with open(abspath, "rb") as fd:
            sha: str = object_hash(fd, b"blob", repo)
            stat: stat_result = os.stat(abspath)
            ctime_s: int = int(stat.st_ctime)
            ctime_ns: int = stat.st_ctime_ns * 10**9
            mtime_s: int = int(stat.st_mtime)
            mtime_ns: int = stat.st_mtime_ns * 10**9
            entry: 'GitIndexEntry' = GitIndexEntry(ctime=(ctime_s, ctime_ns), mtime=(mtime_s, mtime_ns), dev=stat.st_dev,
                                                    mode_type=0b1000, mode_perms=0o644, uid=stat.st_uid, gid=stat.st_gid, fsize=stat.st_size, sha=sha,
                                                    flag_assume_valid=False, flag_stage=False, name=relpath)
            index.append(entry)
    
    index_write(repo, index)

# ------------------------------------------------[commit]--------------------------------------------------

# Signature: None -> configparser
# Purpose: To read git's config to get the name of the user.
def gitconfig_read() -> configparser:
    xdg_config_home: str = os.environ["XDG_CONFIG_HOME"] if "XDG_CONFIG_HOME" in os.environ else "~/.config"
    config_files: list[str] = [
        os.path.expanduser(os.path.join(xdg_config_home, "git/config")),
        os.path.expanduser("~/.gitconfig")
    ]

    config: configparser = configparser.ConfigParser()
    config.read(config_files)
    return config

# Signature: configparser -> Optional[str]
# Purpose: To get and format the user identity.
def gitconfig_user_get(config: configparser) -> Optional[str]:
    if "user" in config:
        if "name" in config["user"] and "email" in config["user"]:
            return f"{config['user']['name']} <{config['user']['email']}>"
    return None

def tree_from_index(repo: 'GitRepository', index: 'GitIndex') -> str:
    contents: dict = dict()
    contents[""] = []

    for entry in index.entries:
        dirname: str = os.path.dirname(entry.name)
        key: str = dirname
        while key != "":
            if not key in contents:
                contents[key] = []
            key = os.path.dirname(key)
        
        contents[dirname].append(entry)

    sorted_paths = sorted(contents.keys(), key=len, reverse=True)
    sha = None

    for path in sorted_paths:
        tree: GitTree = GitTree()
        for entry in contents[path]:
            if isinstance(entry, GitIndexEntry):
                leaf_mode: bytes = f"{entry.mode_type:02o}{entry.mode_perms:04o}".encode("ascii")
                leaf: GitTreeLeaf = GitTreeLeaf(mode = leaf_mode, path=os.path.basename(entry.name), sha=entry.sha)
            else:
                leaf = GitTreeLeaf(mode=b"040000", path=entry[0], sha=entry[1])
            tree.items.append(leaf)

        sha: str = object_write(tree, repo)
        parent: str = os.path.dirname(path)
        base: str = os.path.basename(path)
        contents[parent].append((base, sha))
    
    return sha

# Signature: GitRepository -> str
# Purpose: To create a commit object.
def create_commit(repo: GitRepository, tree: str, parent: str, author: str, timestamp: datetime, message: str) -> str:
    commit: GitCommit = GitCommit()
    commit.kvlm[b'tree'] = tree.encode("ascii")
    if parent:
        commit.kvlm[b'parent'] = parent.encode("ascii")
    
    message = message.strip() + "\n"
    offset: int = int(timestamp.astimezone().utcoffset().total_seconds())
    hours: int = offset // 3600
    minutes: int = (offset % 3600) // 60
    timezone: str = "{}{:02}{:02}".format("+" if offset > 0 else "-", hours, minutes)
    author = author + timestamp.strftime(" %s ") + timezone

    commit.kvlm[b'author'] = author.encode("utf8")
    commit.kvlm[b'committer'] = author.encode("uft8")
    commit.kvlm[None] = message.encode("utf8")

    return object_write(commit, repo)

# Signature: Namespace -> None
# Purpose: Extracts the argument from the CLI and delegates to the commit function.
def cmd_commit(args: Namespace) -> None:
    repo: 'GitRepository' = GitRepository.repo_find()
    index: 'GitIndex' = index_read(repo)
    tree: 'GitTree' = tree_from_index(repo, index)
    commit: str = create_commit(repo, tree, object_find(repo, "HEAD"), gitconfig_user_get(gitconfig_read()), datetime.now(), args.message)
    active_branch: Union[bool, str] = branch_get_active(repo)
    if active_branch:
        with open(GitRepository.repo_find(repo, os.path.join("refs/heads", active_branch)), "w") as fd:
            fd.write(commit + "\n")
    else:
        with open(GitRepository.repo_find(repo, "HEAD"), "w") as fd:
            fd.write("\n")