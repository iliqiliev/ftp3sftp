# ftp3sftp - A simple FTP to SFTP bridge


## Usecase
FTP is a protocol that was introduced in the 80's and today has the major problem of non-encrypted communication. Due to this problem, today there are two well-known advancements of the protocol: FTPS and SFTP.
Unfortunately, there are still legacy systems in the wild that can only communicate with FTP servers. Depending on the importance and maintenance possibilities of the system, the function of working with one of the encrypted variants cannot be implemented with a realistic effort. If no middleware is then available, there are few options.
This is where _ftp3sftp_ comes in and reveals a way to enable communication via SFTP without having to make major changes to the legacy system.

## How _ftp3sftp_ works
_ftp3sftp_ itself starts an FTP server to which an FTP client (for example the legacy system) can connect.
But in the background a connection to a SFTP server is established after a successful login on the FTP server. All information that the FTP client receives actually comes from the SFTP server. They are passed through directly in both directions. This also means that if the FTP client uploads a file, for example, and receives feedback from _ftp3sftp_ that the file has been successfully transferred, the client can be sure that the file has actually arrived on the SFTP server.

If the FTP client (for example, the legacy system) and _ftp3sftp_ are running on the same machine or at least on the same network, and the target SFTP server is only accessible via the Internet, it can thus be ensured that the data transfer via the Internet is appropriately encrypted using the SFTP protocol.

## How to install _ftp3sftp_
_ftp3sftp_ is a Python 3 module. You can install it like:
```sh
uv tool install ftp3sftp
```
### Windows special
While installing not .exe files is still a mystery for some windows users, I created another [repository](https://gitlab.com/sparrow.242.de/ftp3sftp-windows-binaries/-/tree/main) to hold .exe files which were created using [pyinstaller](https://pyinstaller.org/en/stable/).
If you want to run _ftp3sftp_ as a service, you should take a look to [nssm](https://nssm.cc), what is a easy way to run any programs as a service.


## How to use _ftp3sftp_

### Command line arguments
We imagine the following situation:
A legacy software is configured to connect to an FTP server connected at the following URL: `127.0.0.1:21` as user `ftp-user` and password `secret`. The software also expects it to write to the following directory as its home directory: `/home/ftp-user`.
The bridge should connect to your SFTP server, which can be reached at `external-sftp-server:22`. It should connect with the user `sftp-user` and the password `1234512`. On the SFTP server `/home/sftp-user` is the home directory.
Also, a log is to be written to the `/log/ftp3sftp` directory.

For this configuration you have to call ftp3sftp with this arguments:
```ftp3sftp --ftp ftp-user:secret@127.0.0.1:21:/home/ftp-user --sftp sftp-user:1234512@external-sftp-server:22:/home/sftp-user --logdir /log/ftp3sftp```

Both, the `--ftp` and the `--sftp` parameter have the same format: `username:password@host:port:/homedirectory`. Note: the homedirectory can also be something like `/`. It depends on the server or client configuration.

You can see the all command line arguments by using `--help`.

### Store command line arguments in a textfile

You can store your command line options in a textfile. For the example above it could contain the following data:
```
--ftp
ftp-user:secret@127.0.0.1:21:/home/ftp-user
--sftp
sftp-user:1234512@external-sftp-server:22:/home/sftp-user
--logdir
/log/ftp3sftp
```
Whe you do so, your only paramter to ftp3sftp could be the path to the file with a `as` prefix. If your configuration is in `/etc/ftp3sftp.conf` you can call ftp3sftp like this:
```ftp3sftp @/etc/ftp3sftp.conf```
So it will read its command line arguments from the file.
