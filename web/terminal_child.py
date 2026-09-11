import fcntl, os, termios
os.setsid()
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
os.execv('/bin/zsh', ['zsh', '-i'])
