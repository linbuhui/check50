import signal
import os
import subprocess
import imp
import sys
import argparse
import tempfile
import shutil
import errno
import inspect
import traceback

from pprint import pprint

import attr
from termcolor import cprint

from . import internal
from .api import Failure
from .runner import CheckRunner, check_names, Status


class InternalError(Exception):
    """Error during execution of check50."""

    def __init__(self, msg):
        self.msg = msg


def handler(number, frame):
    cprint("Check cancelled.", "red")
    sys.exit(1)


def excepthook(cls, exc, tb):
    # Class is a BaseException, better just quit.
    if not issubclass(cls, Exception):
        print()
        return

    if cls is InternalError:
        cprint(exc.msg, "red", file=sys.stderr)
    elif cls is FileNotFoundError:
        cprint(f"{exc.filename} not found", "red", file=sys.stderr)
    else:
        cprint("Sorry, something's wrong! Let sysadmins@cs50.harvard.edu know!", "red", file=sys.stderr)

    if main.args.debug:
        traceback.print_exception(cls, exc, tb)


sys.excepthook = excepthook


def import_checks(checks_dir, identifier):
    """
    Given an identifier of the form path/to/check@org/repo, clone
    the checks from github.com/org/repo (defaulting to cs50/checks
    if there is no @) into main.args.checkdir. Then extract child
    of Check class from path/to/check/check50/__init__.py and return it
    """

    try:
        slug, repo = identifier.split("@")
    except ValueError:
        slug, repo = identifier, "cs50/checks"

    try:
        org, repo = repo.split("/")
    except ValueError:
        raise InternalError(
            "expected repository to be of the form username/repository, but got \"{}\"".format(repo))
    checks_root = os.path.join(checks_dir, org, repo)
    internal.check_dir = os.path.join(checks_root, slug.replace("/", os.sep), "check50")

    if not main.args.offline:
        if os.path.exists(checks_root):
            command = ["git", "-C", checks_root, "pull", "origin", "master"]
        else:
            command = ["git", "clone", "https://github.com/{}/{}".format(org, repo), checks_root]

        # Can't use subprocess.DEVNULL because it requires python 3.3.
        stdout = stderr = None if main.args.debug else open(os.devnull, "wb")

        # Update checks via git.
        try:
            subprocess.check_call(command, stdout=stdout, stderr=stderr)
        except subprocess.CalledProcessError:
            raise InternalError("failed to clone checks")

    # Install any dependencies from requirements.txt either in the root of the
    # repository or in the directory of the specific check.
    for dir in [checks_root, os.path.dirname(internal.check_dir)]:
        requirements = os.path.join(dir, "requirements.txt")
        if os.path.exists(requirements):
            pip = ["pip", "install", "-r", requirements]

            # If we are not in a virtualenv, we need --user
            if not hasattr(sys, "real_prefix") and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
                pip.append("--user")

            try:
                subprocess.check_call(pip, stdout=stdout, stderr=stderr)
            except subprocess.CalledProcessError:
                raise InternalError("failed to install dependencies in ({})".format(
                    requirements[len(checks_dir) + 1:]))

    try:
        # Import module from file path directly.
        module = imp.load_source(slug, os.path.join(internal.check_dir, "__init__.py"))
    except FileNotFoundError:
        raise InternalError("invalid identifier")

    return module


def print_results(results, log=True):
    for result in results:
        if result.status is Status.Pass:
            cprint(f":) {result.description}", "green")
        elif result.status is Status.Fail:
            cprint(f":( {result.description}", "red")
            if result.rationale is not None:
                cprint(f"    {result.rationale}", "red")
        elif result.status is Status.Skip:
            cprint(f":| {result.description}", "yellow")
            cprint(f"    {result.rationale or 'check skipped'}", "yellow")

        if log:
            for line in result.log:
                print(f"    {line}")


def main():
    signal.signal(signal.SIGINT, handler)

    # Parse command line arguments.
    parser = argparse.ArgumentParser()
    parser.add_argument("identifier")
    parser.add_argument("files", nargs="*", default=os.listdir("."))
    parser.add_argument("-j", "--json",
                        action="store_true",
                        help="display machine-readable JSON output")
    parser.add_argument("-l", "--local",
                        action="store_true",
                        help="run checks locally instead of uploading to cs50")
    parser.add_argument("--offline",
                        action="store_true",
                        help="run checks completely offline (implies --local)")
    parser.add_argument("--checkdir",
                        action="store",
                        default="~/.local/share/check50",
                        help="specify directory containing the checks "
                             "(~/.local/share/check50 by default)")
    parser.add_argument("--log",
                        action="store_true",
                        help="display more detailed information about check results")
    parser.add_argument("-d", "--debug",
                        action="store_true",
                        help="display the full tracebacks of any errors (also implies --log)")

    main.args = parser.parse_args()
    main.args.checkdir = os.path.abspath(os.path.expanduser(main.args.checkdir))

    if main.args.offline:
        main.args.local = True

    if main.args.debug:
        main.args.log = True

    checks_module = import_checks(main.args.checkdir, main.args.identifier)

    results = CheckRunner(checks_module).run(main.args.files)
    print_results(results[name] for name in check_names)
    # for check_name in check_names:
        # pprint({check_name : attr.asdict(results[check_name])})


    # Get list of results from TestResult class.
    # results = result.results

    # Print the results.
    #if config.args.debug:
    #    print_json(results)
    #else:
    #    print_results(results, log=config.args.log)

if __name__ == "__main__":
    main()
