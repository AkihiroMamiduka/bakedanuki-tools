# coding: utf-8
# Mayaは全userSetup.pyを同じ__main__辞書で実行するため名前を残さない
try:
    __import__(
        "bd_tools._startup", fromlist=("schedule_menu_install",)
    ).schedule_menu_install()
except Exception:
    __import__("traceback").print_exc()
