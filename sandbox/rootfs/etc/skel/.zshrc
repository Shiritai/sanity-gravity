# Minimal zsh config for the developer sandbox.
# The mere existence of this file suppresses the zsh-newuser-install wizard
# that would otherwise run on the first interactive shell (fresh containers
# have no home yet, but zsh is the user's default shell).
setopt HIST_IGNORE_DUPS
HISTSIZE=10000
SAVEHIST=10000
HISTFILE="$HOME/.zsh_history"
export EDITOR=vim
alias ls='ls --color=auto'
