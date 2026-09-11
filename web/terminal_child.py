import fcntl, os, termios, json
os.setsid()
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
command=os.environ.pop('LAB_PTY_COMMAND',None)
if command:
    argv=json.loads(command)
    os.execvp(argv[0],argv)
os.execv('/bin/zsh', ['zsh', '-i'])
