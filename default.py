import sys

import xbmc
import xbmcgui

import resources.lib.utils as utils


def main():
    """Build Manager entrypoint. Invoked by Kodi when the add-on is run."""
    dialog = xbmcgui.Dialog()
    dialog.ok(
        utils.getString(32000),
        utils.getString(32010),
    )


if __name__ == '__main__':
    main()
