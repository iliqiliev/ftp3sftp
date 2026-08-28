# ftp3sftp.py - A FTP to SFTP bridge
# Copyright (C) 2026  Iliya Iliev     <iliq0000@proton.me>
# Copyright (C) 2023  Sebastian Meyer <sparrow.242.de@gmail.com>
# You should have received a copy of the GNU General Public License V3
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import argparse
import logging
import pathlib
from collections import namedtuple
from datetime import datetime as DateTime
from datetime import timezone
from logging.handlers import TimedRotatingFileHandler
from stat import S_ISDIR
from textwrap import dedent

from paramiko import SFTPClient, Transport
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


def main():
    print(
        dedent("""\
        ftp3sftp.py (Version 0.7.1)
        Copyright (C) 2026  Iliya Iliev     <iliq0000@proton.me>
        Copyright (C) 2023  Sebastian Meyer <sparrow.242.de@gmail.com>
        Licensed under GNU GPL (https://www.gnu.org/licenses/gpl-3.0.html)
        This program comes with ABSOLUTELY NO WARRANTY.
        This is free software, and you are welcome to redistribute it
        under certain conditions.""")
    )

    options = parse_arguments_options()
    setup_logger(options.loglevel, options.logdir, options.keeplog)
    logging.info("ftp3sftp is starting...")
    authorizer = Authorizer()
    authorizer.add_user(
        options.ftp.username,
        options.ftp.password,
        perm="elradfmwMT",
        homedir=options.ftp.path or f"/home/{options.ftp.username}",
    )
    handler = FTP2SFTPHandler
    handler.authorizer = authorizer
    handler.abstracted_fs = SFTPConnectedFS
    sftp_config = {
        "host": options.sftp.host,
        "port": options.sftp.port,
        "username": options.sftp.username,
        "password": options.sftp.password,
        "basedir": options.sftp.path,
    }
    handler.sftp_config = sftp_config
    server = FTPServer((options.ftp.host, options.ftp.port), handler)
    server.serve_forever()


Address = namedtuple("Address", ("host", "port", "username", "password", "path"))


def connect_sftp(
    host: str, port: int, username: str, password: str
) -> tuple[Transport, SFTPClient]:
    """
    This functions connects to a SFTP Server and returs a tuple with
    a paramiko/SSH-transport object and an SFTP-Client object.
    """

    logging.info(f"Try to connect SFTP: {host}:{port} as user '{username}'")

    transport = Transport((host, port))
    transport.connect(None, username, password)

    sftp_client = SFTPClient.from_transport(transport)

    if sftp_client is None:
        raise ValueError("Failed to create SFTP client.")

    return (transport, sftp_client)


class Authorizer(DummyAuthorizer):
    """
    Subclass of the dummy example to have the option to
    manage users without a local directory on the filesystem
    """

    def add_user(
        self,
        username,
        password,
        homedir,
        perm="elr",
        msg_login="Login successful.",
        msg_quit="Goodbye.",
    ):
        """
        Add a user to the virtual users table.

        We overwrite the function because we don't need a homedir
        on the local filesystem.
        """

        if self.has_user(username):
            raise ValueError("user %r already exists" % username)
        self._check_permissions(username, perm)
        self.user_table[username] = {
            "pwd": str(password),
            "perm": perm,
            "operms": {},
            "msg_login": str(msg_login),
            "msg_quit": str(msg_quit),
            "home": homedir,
        }


class FTP2SFTPHandler(FTPHandler):
    # this parameter has to be set from outside before the
    # initialization through the server.
    # This kind of monkey patching is more stable than also
    # subclassing the server only to pass this information.
    sftp_config = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def handle_close(self):
        logging.debug("call handle_close")
        if self.fs is not None:
            self.fs.close_sftp_connection()
        super().handle_close()


class SFTPConnectedFS:
    def __init__(self, home, handler):
        self.handler = handler
        self._root = home
        logging.info(f"Home directory for the FTP user: {self._root}")
        self._cwd = self._root
        self._sftp_root = handler.sftp_config["basedir"] or "/"
        self.ssh_transport, self.sftp_client = connect_sftp(
            handler.sftp_config["host"],
            handler.sftp_config["port"],
            handler.sftp_config["username"],
            handler.sftp_config["password"],
        )

    def chdir(self, path):
        new_path = path
        logging.debug(f"call chdir : {path} -> {new_path}")
        self.sftp_client.chdir(new_path)
        self.cwd = self.fs2ftp(new_path)

    def close_sftp_connection(self):
        logging.debug("call close_sftp_connection")
        self.ssh_transport.close()

    @property
    def cwd(self):
        logging.debug(f"call cwd : -> {self._cwd}")
        return self._cwd

    @cwd.setter
    def cwd(self, path):
        # We need a little workaround here to resolve posix files (for the
        # SFTP server) on a not posix system. We use pathlib and cut of the
        # drive letter if it appears.

        new_cwd_path = pathlib.Path(path).resolve()
        new_cwd = new_cwd_path.as_posix()
        new_cwd = new_cwd.removeprefix(new_cwd_path.drive)
        logging.debug(f"call set cwd : {path} -> {new_cwd}")
        self._cwd = new_cwd

    def format_mlsx(self, basedir: str, listing, perms, facts, ignore_err=True):
        logging.debug(
            f"call format_mlsx : {basedir}, {listing}, {perms}, {facts}, {ignore_err} -> ..."
        )
        for entry in self.sftp_client.listdir_iter(basedir):
            values = []
            if "type" in facts:
                values.append("type=dir" if S_ISDIR(entry.st_mode) else "type=file")
            if "perm" in facts:
                values.append("perm=r")
            if "size" in facts:
                values.append(f"size={entry.st_size}")
            if "modify" in facts:
                dt = DateTime.fromtimestamp(entry.st_mtime, tz=timezone.utc)
                ts = dt.strftime("%Y%m%d%H%M%S")
                values.append(f"modify={ts}")
            values.append(f" {entry.filename}\n")
            response = ";".join(values).encode()
            logging.debug(f" response format_mlsx : {response}")
            yield response

    def fs2ftp(self, fspath: str):
        fspath = fspath.removeprefix(".")
        fspath = (
            f"{fspath[len(self._sftp_root) :]}"
            if fspath.startswith(self._sftp_root)
            else fspath
        )
        ftppath = f"{self._root.rstrip('/')}/{fspath.lstrip('/')}"
        logging.debug(f"call fs2ftp : {fspath} -> {ftppath}")
        return ftppath

    def ftp2fs(self, ftppath: str):
        if not ftppath.startswith("/"):
            ftppath = f"{self._cwd}/{ftppath}"
        fspath = (
            f"{ftppath[len(self._root) :]}"
            if ftppath.startswith(self._root)
            else ftppath
        )
        fspath = f"{self._sftp_root.rstrip('/')}/{fspath.lstrip('/')}"
        logging.debug(f"call ftp2fs : {ftppath} -> {fspath}")
        return fspath

    def getmtime(self, path: str):
        stat = self.sftp_client.stat(path)
        mtime = stat.st_mtime
        logging.debug(f"call getmtime : {path} {mtime}")
        return mtime

    def isdir(self, path: str):
        is_dir = None
        try:
            stat = self.sftp_client.stat(path)
        except FileNotFoundError:
            is_dir = False
        if is_dir is None:
            is_dir = S_ISDIR(stat.st_mode)
        logging.debug(f"call isdir : {path} -> {is_dir}")
        return is_dir

    def isfile(self, path: str):
        is_file = None
        try:
            stat = self.sftp_client.stat(path)
        except FileNotFoundError:
            is_file = False
        if is_file is None:
            is_file = not S_ISDIR(stat.st_mode)
        logging.debug(f"call isfile : {path} -> {is_file}")
        return is_file

    def lexists(self, path: str):
        exists = True
        try:
            _ = self.sftp_client.stat(path)
        except FileNotFoundError:
            exists = False
        logging.debug(f"call lexists : {path} -> {exists}")
        return exists

    def listdir(self, path: str):
        listing = self.sftp_client.listdir(path)
        logging.debug(f"call listdir : {path} -> {listing}")
        return listing

    def mkdir(self, path: str):
        logging.debug(f"call mkdir : {path}")
        self.sftp_client.mkdir(path)

    def open(self, filename: str, mode: str):
        logging.debug(f"call open : {filename}, {mode}")

        sftp_open = self.sftp_client.open(filename, mode)
        # the .name property of the handle is used by the FTP library.
        sftp_open.name = filename

        return sftp_open

    def realpath(self, path: str):
        if not path.startswith("/"):
            cwd = self._cwd.removesuffix("/")
            realpath = f"{cwd}/{path}"
        else:
            realpath = path

        realpath = self.ftp2fs(realpath)
        logging.debug(f"call realpath : {path} -> {realpath}")
        return realpath

    def rename(self, src: str, dst: str):
        logging.debug(f"call rename : {src} {dst}")
        self.sftp_client.rename(src, dst)

    def remove(self, path: str):
        logging.debug(f"call remvoe : {path}")
        self.sftp_client.remove(path)

    def rmdir(self, path: str):
        logging.debug(f"call rmdir : {path}")
        self.sftp_client.rmdir(path)

    @property
    def root(self):
        logging.debug(f"call root : {self._root}")
        return self._root

    def utime(self, path: str, timeval: float):
        logging.debug(f"call utime : {path} {timeval}")
        self.sftp_client.utime(path, (timeval, timeval))

    def validpath(self, path: str):
        is_valid = True
        logging.debug(f"call validpath : {path} -> {is_valid}")
        return is_valid


def setup_logger(loglevel: int | str, logdir, keeplog):
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger()
    logger.setLevel(loglevel)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(loglevel)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.info(f"Logging is active on level {logging.getLevelName(logger.level)}")
    if logdir:
        logfile = logdir / "ftp3sftp_log.txt"
        handler = TimedRotatingFileHandler(
            logfile,
            when="d",
            interval=1,
            backupCount=keeplog,
        )
        handler.setLevel(loglevel)
        handler.setFormatter(formatter)
        logger.addHandler(handler)


def parse_address(address):
    user_part, server_part = address.split("@")
    user, password = user_part.split(":")
    server_part_elements = server_part.split(":")
    host, port = server_part_elements[:2]
    path = server_part_elements[2] if len(server_part_elements) > 2 else None
    return Address(host, int(port), user, password, path)


def parse_arguments_options():
    parser = argparse.ArgumentParser(
        fromfile_prefix_chars="@",
    )
    parser.add_argument(
        "--ftp",
        type=parse_address,
        required=True,
        help="Information where to start the FTP server: username:password@host:port:/homedir",
    )
    parser.add_argument(
        "--sftp",
        type=parse_address,
        required=True,
        help="Information how to connect the SFTP server: username:password@host:port:/homedir",
    )
    parser.add_argument(
        "--loglevel",
        type=str,
        default="INFO",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"],
        help="Set the loglevel for logging. (Default: INFO)",
    )
    parser.add_argument(
        "--logdir",
        type=pathlib.Path,
        default=None,
        help="Directory to write the log. Logs will be sperated in files daily",
    )
    parser.add_argument(
        "--keeplog",
        type=int,
        default=7,
        help="How long (in days) keep the logfile if logdir is set (Default: 7)",
    )
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    main()
