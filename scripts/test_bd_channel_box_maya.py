# coding: utf-8
"""独立したMaya本体でbdChannelBoxの表示と終了を検証する。"""

from __future__ import annotations

import argparse
import base64
import faulthandler
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from bd_tools.bd_channel_box.ui import ChannelBoxWindow
    from bd_tools.bd_channel_box.widget import (
        AttributeRowWidget,
        AttributeStateRowWidget,
    )
    from bd_util.ui import qt

_OUTPUT_VARIABLE = "BAKEDANUKI_TOOLS_UI_QA_OUTPUT"
_PHASE_VARIABLE = "BAKEDANUKI_TOOLS_UI_QA_PHASE"
_PREPARE_RESTART_VARIABLE = "BAKEDANUKI_TOOLS_UI_QA_PREPARE_RESTART"
_PERSISTED_STEP = 0.5
_STARTUP_IDLE_COMMAND = (
    "import __main__; "
    "__main__._bd_tools_bd_channel_box_qa_session.begin_when_idle()"
)


def _write_json(path: Path, value: object) -> None:
    """検証結果をUTF-8のJSONへ保存する。"""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class _MayaSmokeSession:
    """Qt event loopを進めながら独立sceneでUI lifecycleを確認する。"""

    def __init__(self, output: Path) -> None:
        """結果保存先と各段階で保持するWindowを初期化する。"""
        self.output = output
        self._phase = os.environ.get(_PHASE_VARIABLE, "initial")
        sys.excepthook = self._record_slot_error
        self._trace_file = (output / f"python-stacks-{self._phase}.log").open(
            "w", encoding="utf-8"
        )
        # 起動と反復計測の通常所要時間を超えて停止した場合だけstackを採取する
        faulthandler.dump_traceback_later(
            120, repeat=True, file=self._trace_file
        )
        self.window: ChannelBoxWindow | None = None
        self.nodes: list[str] = []
        self.baseline_callbacks: dict[str, int] = {}
        self.steps: list[str] = []
        self.screenshots: list[str] = []
        self.measurements: dict[str, float | int] = {}
        self.diagnostics: list[dict[str, object]] = []
        self._value_layout: tuple[int, int, int, int] | None = None
        self._started_at = time.perf_counter()
        self._startup_idle_checks = 0
        self._stage_index = 0
        self._stages = (
            self._setup_scene,
            self._show,
            self._inspect,
            self._inspect_wheel_setting,
            self._inspect_attribute_search,
            self._inspect_native_wheel_controls,
            self._float_dock,
            self._inspect_floating,
            self._redock,
            self._inspect_redocked,
            self._reset_dock_layout,
            self._refresh_from_context_menu,
            self._edit_step,
            self._undo_step_value,
            self._edit_bool,
            self._undo_bool,
            self._inspect_enum_popup,
            self._select_enum_item,
            self._undo_enum,
            self._align_enum,
            self._undo_enum_alignment,
            self._edit_float,
            self._undo_float,
            self._drag_float,
            self._undo_drag,
            self._align_bool,
            self._undo_alignment,
            self._show_state_mode,
            self._edit_display_state,
            self._edit_lock_state,
            self._inspect_mixed_states,
            self._return_to_values,
            self._inspect_filters,
            self._inspect_attribute_order,
            self._inspect_multi_attribute_selection,
            self._inspect_multi_value_controls,
            self._inspect_multi_state_controls,
            self._inspect_clipboard_value_transfer,
            self._inspect_state_sweep,
            self._inspect_lock_sweep,
            self._close,
            self._reopen,
            self._change_selection,
            self._close_for_reload,
            self._reopen_for_reload,
            self._reload,
            self._show_after_reload,
            self._capture_after_reload,
            self._benchmark,
            self._finish,
        )
        if self._phase == "restart":
            self._stages = (
                self._inspect_restart,
                self._setup_scene,
                self._edit_after_restart,
                self._finish,
            )

    def _record_slot_error(
        self,
        error_type: type[BaseException],
        error: BaseException,
        trace: TracebackType | None,
    ) -> None:
        """Qt signal経由で呼出し元へ戻らない例外も検証資料へ記録する。"""
        with (self.output / "python-slot-errors.log").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                "".join(traceback.format_exception(error_type, error, trace))
            )

    def begin_when_idle(self) -> None:
        """Mayaの起動時deferred処理がなくなってから検証を開始する。"""
        from maya import cmds

        from bd_util.ui import qt

        self._startup_idle_checks += 1
        # 実行中の自身もqueue一覧へ残るため、他の起動処理だけを待つ
        pending = [
            command
            for command in (cmds.evalDeferred(list=True) or [])
            if command != _STARTUP_IDLE_COMMAND
        ]
        _write_json(
            self.output / "progress.json",
            {"running": "waiting_for_startup_idle", "pending": pending},
        )
        if pending:
            if (
                self._startup_idle_checks >= 64
                or time.perf_counter() - self._started_at >= 60
            ):
                self._record_state("startup_idle_timeout")
                self._complete(
                    False,
                    "Mayaの起動時deferred処理が終了しませんでした: "
                    f"{pending}",
                )
                return
            self.defer_until_idle()
            return
        self._record_state("startup_idle_complete")
        qt.QTimer.singleShot(0, self.advance)

    @staticmethod
    def defer_until_idle() -> None:
        """起動時の他のidle処理を優先して、検証開始判定を末尾へ予約する。"""
        from maya import cmds

        cmds.evalDeferred(_STARTUP_IDLE_COMMAND, lowestPriority=True)

    def advance(self) -> None:
        """現在の段階を実行し、次の段階をQt event loopへ予約する。"""
        from bd_util.ui import qt

        try:
            stage = self._stages[self._stage_index]
            self._stage_index += 1
            _write_json(
                self.output / "progress.json",
                {"running": stage.__name__, "completed": self.steps},
            )
            self._record_state(f"before:{stage.__name__}")
            stage()
            self._record_state(f"after:{stage.__name__}")
        except Exception:
            self._complete(False, traceback.format_exc())
            return
        if self._stage_index < len(self._stages):
            qt.QTimer.singleShot(250, self.advance)

    def _setup_scene(self) -> None:
        """検証専用sceneを用意し、値が異なる2ノードを選択する。"""
        from maya import cmds

        # 新規process専用の設定ディレクトリか確認してからsceneを作る
        expected = (self.output / "prefs").resolve()
        actual = Path(os.environ["MAYA_APP_DIR"]).resolve()
        if actual != expected or cmds.about(batch=True):
            raise RuntimeError("独立した対話用Maya processで実行してください")
        cmds.file(new=True, force=True)
        # 新規profileの初期設定に依存せず、専用sceneのUndoだけを有効化する
        cmds.undoInfo(state=True, infinity=True)
        if not cmds.undoInfo(query=True, state=True):
            raise RuntimeError("検証sceneのUndoを有効にできません")
        for index in range(2):
            node = cmds.createNode("transform", name=f"bdChannelBoxQA{index}")
            cmds.addAttr(
                node,
                longName="weight",
                attributeType="double",
                minValue=0.0,
                maxValue=1.0,
                keyable=True,
            )
            cmds.setAttr(f"{node}.weight", 0.25 + index * 0.5)
            cmds.addAttr(
                node,
                longName="enabled",
                attributeType="bool",
                keyable=True,
            )
            cmds.setAttr(f"{node}.enabled", bool(index))
            cmds.addAttr(
                node,
                longName="mode",
                attributeType="enum",
                enumName="Negative=-2:Off=0:Preview=5:Final=10",
                keyable=True,
            )
            cmds.setAttr(f"{node}.mode", 5 if index == 0 else -2)
            cmds.addAttr(
                node,
                longName="modeCopy",
                attributeType="enum",
                enumName="Negative=-2:Off=0:Preview=5:Final=10",
                keyable=True,
            )
            cmds.setAttr(f"{node}.modeCopy", 0 if index == 0 else 10)
            cmds.addAttr(
                node,
                longName="hiddenWeight",
                niceName="Previously Hidden Attribute With A Long Name",
                attributeType="double",
            )
            cmds.setAttr(f"{node}.hiddenWeight", 0.2 + index * 0.4)
            self.nodes.append(node)
        cmds.select(self.nodes, replace=True)
        self.steps.append("create_isolated_scene")

    def _show(self) -> None:
        """Maya標準UIの選択処理が完了してから入力Windowを表示する。"""
        from bd_tools import bd_channel_box

        self.baseline_callbacks = self._callback_counts()
        self.window = bd_channel_box.show()
        self.steps.append("show_multiple_selection")

    def _inspect(self) -> None:
        """実Windowの描画と対応Viewの存在を確認して画像を保存する。"""
        from bd_util.ui import BoolCheckBox, EnumComboBox, FloatSliderSpinBox

        window = self._require_window()
        if not window.isVisible():
            raise AssertionError("bdChannelBoxが表示されていません")
        if window.windowTitle() != "bdChannelBox":
            raise AssertionError(
                f"Windowタイトルが不正です: {window.windowTitle()}"
            )
        if not window.findChildren(BoolCheckBox):
            raise AssertionError("boolのCheckBoxが見つかりません")
        if not window.findChildren(FloatSliderSpinBox):
            raise AssertionError("min/max属性のSlider Viewが見つかりません")
        if not window.findChildren(EnumComboBox):
            raise AssertionError("enumのComboBoxが見つかりません")
        if window.widget.scroll_area.horizontalScrollBar().maximum():
            raise AssertionError("入力欄が縮小後のWindow幅に収まりません")
        self._capture("01-multiple-selection.png")
        self.steps.append("inspect_rendered_views")

    def _inspect_wheel_setting(self) -> None:
        """設定メニューを表示し、OFFでは未フォーカスのホイール入力を止める。"""
        from maya import cmds

        from bd_util.ui import EnumComboBox, FloatValueStepSpinBox, qt

        widget = self._require_window().widget
        action = widget.wheel_editing_action
        if action.isChecked():
            raise AssertionError("ホイール編集設定の初期値がOFFではありません")
        if action not in widget.settings_menu.actions():
            raise AssertionError("設定メニューにホイール編集項目がありません")

        # 実メニューのチェック表示を独立したpopup画像として保存する
        menu_position = widget.menu_bar.mapToGlobal(
            qt.QPoint(0, widget.menu_bar.height())
        )
        widget.settings_menu.popup(menu_position)
        self._flush_gui()
        menu_path = self.output / "30-wheel-settings-menu.png"
        if not widget.settings_menu.grab().save(str(menu_path)):
            raise RuntimeError("設定メニュー画像を保存できません")
        self.screenshots.append(str(menu_path))
        widget.settings_menu.close()

        # 初期OFFの値欄・Step欄・enum欄へ未フォーカスのwheelを送る
        view = self._row("translate.translateX").editor
        enum_view = self._row("mode").editor
        if not isinstance(view, FloatValueStepSpinBox):
            raise AssertionError("translateXに値とStepのViewがありません")
        if not isinstance(enum_view, EnumComboBox):
            raise AssertionError("modeにenumのViewがありません")
        widget.mode_combo.setFocus()
        self._flush_gui()
        if (
            not view.spin_box.wheel_requires_focus()
            or not view.step_spin_box.wheel_requires_focus()
            or not enum_view.wheel_requires_focus()
        ):
            raise AssertionError(
                "ホイール編集設定のOFFが属性入力欄へ反映されません"
            )
        value_before = tuple(
            cmds.getAttr(f"{node}.translateX") for node in self.nodes
        )
        enum_before = tuple(
            cmds.getAttr(f"{node}.mode") for node in self.nodes
        )
        step_before = view.singleStep()
        cmds.flushUndo()
        self._wheel(view.spin_box)
        self._wheel(view.step_spin_box)
        self._wheel(enum_view)
        self._flush_gui()
        self._assert_values("translateX", value_before)
        self._assert_values("mode", enum_before)
        if view.singleStep() != step_before:
            raise AssertionError(
                "OFF中の未フォーカスwheelでStepが変わりました"
            )
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("OFF中の未フォーカスwheelでUndoが増えました")
        self._capture("31-wheel-setting-off.png")
        self.steps.append("wheel_setting_menu_and_unfocused_input")

    def _inspect_native_wheel_controls(self) -> None:
        """値欄のネイティブ入力で設定切替・フォーカス・スクロールを確認する。"""
        from maya import cmds

        from bd_util.ui import (
            EnumComboBox,
            FloatSliderSpinBox,
            FloatValueStepSpinBox,
            qt,
        )

        widget = self._require_window().widget
        action = widget.wheel_editing_action
        for path, attribute in (
            ("translate.translateX", "translateX"),
            ("weight", "weight"),
        ):
            # OFF→ON→OFFを同じ値欄へ反映し、Undoでsceneを元に戻す
            for enabled, focused in (
                (False, False),
                (False, True),
                (True, False),
                (False, False),
            ):
                action.setChecked(enabled)
                view = self._row(path).editor
                if not isinstance(
                    view, (FloatValueStepSpinBox, FloatSliderSpinBox)
                ):
                    raise AssertionError(f"数値欄がありません: {path}")
                spin = view.spin_box
                widget.mode_combo.setFocus()
                if focused:
                    spin.setFocus()
                self._flush_gui()
                if spin.hasFocus() != focused:
                    raise AssertionError(f"検証前のフォーカスが不正: {path}")
                before = tuple(
                    cmds.getAttr(f"{node}.{attribute}") for node in self.nodes
                )
                cmds.flushUndo()
                self._wheel(spin)
                self._flush_gui()
                if enabled or focused:
                    self._assert_values(
                        attribute,
                        tuple(value + spin.singleStep() for value in before),
                    )
                    cmds.undo()
                    self._flush_gui()
                else:
                    if spin.hasFocus():
                        raise AssertionError(
                            f"OFF中のwheelがフォーカスを取得しました: {path}"
                        )
                    if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                        raise AssertionError(
                            f"OFF中にUndoが増えました: {path}"
                        )
                self._assert_values(attribute, before)

        # enum欄もOFF→ON→OFFで、フォーカス中またはONの場合だけ変更する
        for enabled, focused in (
            (False, False),
            (False, True),
            (True, False),
            (False, False),
        ):
            action.setChecked(enabled)
            enum_view = self._row("mode").editor
            if not isinstance(enum_view, EnumComboBox):
                raise AssertionError("modeにenumのViewがありません")
            widget.mode_combo.setFocus()
            if focused:
                enum_view.setFocus()
            self._flush_gui()
            if enum_view.hasFocus() != focused:
                raise AssertionError("enum検証前のフォーカスが不正です")
            before = tuple(cmds.getAttr(f"{node}.mode") for node in self.nodes)
            cmds.flushUndo()
            self._wheel(enum_view)
            self._flush_gui()
            if enabled or focused:
                self._assert_values("mode", (0, 0))
                cmds.undo()
                self._flush_gui()
            else:
                if enum_view.hasFocus():
                    raise AssertionError(
                        "OFF中のwheelがenum欄のフォーカスを取得しました"
                    )
                if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                    raise AssertionError("OFF中のenum wheelでUndoが増えました")
            self._assert_values("mode", before)

        # 行数に対して表示域を狭め、値欄から親の一覧へwheelが届くことを確認する
        table = widget.table_view
        previous_maximum = table.maximumHeight()
        try:
            table.setMaximumHeight(140)
            self._flush_gui()
            for path in ("translate.translateX", "weight", "mode"):
                row = self._row(path)
                view = row.editor
                if isinstance(view, FloatValueStepSpinBox):
                    fields = (view.spin_box, view.step_spin_box)
                elif isinstance(view, FloatSliderSpinBox):
                    fields = (view.spin_box,)
                elif isinstance(view, EnumComboBox):
                    fields = (view,)
                else:
                    raise AssertionError(f"ホイール入力欄がありません: {path}")
                model = table.model()
                if model is None:
                    raise AssertionError("一覧のmodelがありません")
                index = model.index(widget.row_widgets.index(row), 0)
                for field in fields:
                    table.scrollTo(
                        index,
                        qt.QtWidgets.QAbstractItemView.ScrollHint.PositionAtTop,
                    )
                    widget.mode_combo.setFocus()
                    self._flush_gui()
                    scrollbar = table.verticalScrollBar()
                    scroll_before = scrollbar.value()
                    value_before = (
                        field.currentIndex()
                        if isinstance(field, EnumComboBox)
                        else field.value()
                    )
                    if scroll_before <= scrollbar.minimum():
                        raise AssertionError(
                            "検証用のスクロール余地がありません"
                        )
                    self._wheel(field)
                    self._flush_gui()
                    value_after = (
                        field.currentIndex()
                        if isinstance(field, EnumComboBox)
                        else field.value()
                    )
                    if value_after != value_before or field.hasFocus():
                        raise AssertionError(
                            "OFF中のスクロールが値欄を操作しました"
                        )
                    if scrollbar.value() >= scroll_before:
                        raise AssertionError("値欄のwheelが一覧へ伝わりません")
        finally:
            table.setMaximumHeight(previous_maximum)
            table.verticalScrollBar().setValue(0)
            self._flush_gui()
        self.steps.append("native_wheel_value_focus_toggle_and_parent_scroll")

    def _inspect_attribute_search(self) -> None:
        """検索欄の3表示方針と、既存行だけを絞る検索結果を確認する。"""
        from maya import cmds

        from bd_util.ui import qt

        widget = self._require_window().widget
        actions = widget.search_visibility_actions
        if widget.search_visibility != "all_only":
            raise AssertionError("検索欄の初期表示方針が不正です")
        if widget.search_edit.isVisible():
            raise AssertionError("全て以外で検索欄が表示されています")

        # 3項目を実際のMenuで表示し、文字切れと初期チェックを保存する
        menu_position = widget.menu_bar.mapToGlobal(
            qt.QPoint(0, widget.menu_bar.height())
        )
        widget.search_visibility_menu.popup(menu_position)
        self._flush_gui()
        menu_path = self.output / "36-search-visibility-menu.png"
        if not widget.search_visibility_menu.grab().save(str(menu_path)):
            raise RuntimeError("検索欄表示メニュー画像を保存できません")
        self.screenshots.append(str(menu_path))
        widget.search_visibility_menu.close()

        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("all")
        )
        self._flush_gui()
        if not widget.search_edit.isVisible():
            raise AssertionError("全てで検索欄が表示されません")
        rows = widget.row_widgets
        translate_x = next(
            row.key
            for row in widget.table_view.rows
            if row.key[0] == "translate.translateX"
        )
        translate_y = next(
            row.key
            for row in widget.table_view.rows
            if row.key[0] == "translate.translateY"
        )
        widget.table_view.select_keys((translate_x, translate_y))
        cmds.flushUndo()

        # 正式path検索はBindingを作り直さず、見えない選択だけを解除する
        widget.search_edit.setText("TRANSLATE.TRANSLATEX")
        self._flush_gui()
        visible = tuple(
            row.key[0]
            for index, row in enumerate(widget.table_view.rows)
            if not widget.table_view.isRowHidden(index)
        )
        if visible != ("translate.translateX",):
            raise AssertionError(f"検索結果が不正です: {visible}")
        if widget.row_widgets != rows:
            raise AssertionError("検索で属性行またはBindingが再生成されました")
        if widget.table_view.selected_keys() != (translate_x,):
            raise AssertionError("検索で隠れた属性が選択へ残りました")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("属性検索でUndoが増えました")
        self._capture("37-attribute-search.png")

        # 非表示中は文字列を維持しながら、見えない検索条件を無効にする
        actions["never"].setChecked(True)
        self._flush_gui()
        if widget.search_edit.isVisible() or any(
            widget.table_view.isRowHidden(index)
            for index in range(len(widget.table_view.rows))
        ):
            raise AssertionError("非表示中も検索条件が適用されています")
        if widget.search_edit.text() != "TRANSLATE.TRANSLATEX":
            raise AssertionError("非表示への切替で検索文字列が失われました")

        actions["always"].setChecked(True)
        self._flush_gui()
        if not widget.search_edit.isVisible():
            raise AssertionError("常に表示で検索欄が表示されません")
        if sum(action.isChecked() for action in actions.values()) != 1:
            raise AssertionError("検索欄の表示方針が排他的ではありません")

        # 後続工程へ初期条件を戻し、検索文字列自体は保存対象にしない
        actions["all_only"].setChecked(True)
        widget.search_edit.clear()
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("visible")
        )
        self._flush_gui()
        self.steps.append("attribute_search_and_visibility_modes")

    def _float_dock(self) -> None:
        """初回の右ドックを確認し、Maya標準のfloatingへ切り替える。"""
        from maya import cmds
        from bd_tools import bd_channel_box

        name = bd_channel_box.WORKSPACE_CONTROL_NAME
        if not cmds.workspaceControl(name, query=True, exists=True):
            raise AssertionError("workspaceControlが作成されていません")
        if (
            cmds.workspaceControl(name, query=True, label=True)
            != "bdChannelBox"
        ):
            raise AssertionError("workspaceControlのタイトルが不正です")
        if cmds.workspaceControl(name, query=True, floating=True):
            raise AssertionError("初回表示がドッキングされていません")
        if bd_channel_box.show() is not self._require_window():
            raise AssertionError("showでWindowが重複生成されました")
        self._capture_maya("05-docked.png")
        cmds.workspaceControl(name, edit=True, floating=True)

    def _inspect_floating(self) -> None:
        """floating後も同じ入力と監視が生存し、内容を表示できることを確認する。"""
        from maya import cmds
        from bd_tools import bd_channel_box

        if not cmds.workspaceControl(
            bd_channel_box.WORKSPACE_CONTROL_NAME, query=True, floating=True
        ):
            raise AssertionError("floatingへ切り替わりません")
        window = self._require_window()
        if window.widget.controller.is_disposed or not window.isVisible():
            raise AssertionError("floatingへの移動で入力が終了しました")
        self._capture("06-floating-content.png")
        self.steps.append("dock_to_floating_preserves_content")

    def _redock(self) -> None:
        """floatingからMaya右側の既存パネルとタブ化する。"""
        from maya import cmds
        from bd_tools import bd_channel_box

        cmds.workspaceControl(
            bd_channel_box.WORKSPACE_CONTROL_NAME,
            edit=True,
            dockToMainWindow=("right", True),
        )

    def _inspect_redocked(self) -> None:
        """再ドッキング後も同じWindowで入力を継続できることを確認する。"""
        from maya import cmds
        from bd_tools import bd_channel_box

        if cmds.workspaceControl(
            bd_channel_box.WORKSPACE_CONTROL_NAME, query=True, floating=True
        ):
            raise AssertionError("Mayaへ再ドッキングできません")
        if bd_channel_box.show() is not self._require_window():
            raise AssertionError("再ドッキングでWindowが重複しました")
        self.steps.append("redock_to_maya_tab")

    def _reset_dock_layout(self) -> None:
        """配置resetが旧入力を破棄し、新しい右ドックへ戻すことを確認する。"""
        from maya import cmds
        from bd_tools import bd_channel_box
        from bd_util.ui import FloatSliderSpinBox, qt

        old_window = self._require_window()
        old_controller = old_window.widget.controller
        self.window = bd_channel_box.reset_layout()
        self._flush_gui()
        if not old_controller.is_disposed or qt.isValid(old_window):
            raise AssertionError(
                "配置reset後に旧Windowまたは入力が残っています"
            )
        if cmds.workspaceControl(
            bd_channel_box.WORKSPACE_CONTROL_NAME, query=True, floating=True
        ):
            raise AssertionError("配置reset後に右ドックへ戻りません")
        if self._require_window().widget.wheel_editing_action.isChecked():
            raise AssertionError(
                "配置resetでホイール編集設定が初期化されました"
            )
        self._assert_values("weight", (0.25, 0.75))
        slider_view = self._row("weight").editor
        if not isinstance(slider_view, FloatSliderSpinBox):
            raise AssertionError("weight行にSlider付きViewがありません")
        if not slider_view.spin_box.wheel_requires_focus():
            raise AssertionError(
                "配置reset後のSlider値欄へホイール編集設定が反映されません"
            )
        self._require_window().widget.mode_combo.setFocus()
        self._wheel(slider_view.spin_box)
        self._flush_gui()
        self._assert_values("weight", (0.25, 0.75))
        self.steps.append("reset_layout_recreates_right_dock")

    def _refresh_from_context_menu(self) -> None:
        """属性名の右クリックメニューから更新し、値とUndoを維持する。"""
        from maya import cmds

        from bd_util.ui import qt

        row = self._row("weight")
        cmds.flushUndo()
        self._open_context_menu(row.name_label)
        if not row.context_menu.isVisible():
            raise AssertionError("属性名からメニューを開けません")
        row.context_menu.setActiveAction(row.refresh_action)
        self._key(row.context_menu, qt.Qt.Key.Key_Return)
        self._flush_gui()
        if self._row("weight") is row:
            raise AssertionError("メニューから表示が更新されません")
        self._assert_values("weight", (0.25, 0.75))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("メニューの表示更新でUndo履歴が増えました")
        self.steps.append("context_menu_refresh_only_reads_values")

    def _edit_step(self) -> None:
        """右クリックのStep設定と、正本を変えない実入力・保存を確認する。"""
        from maya import cmds

        from bd_util.ui import FloatValueStepSpinBox, qt

        row = self._row("translate.translateX")
        view = row.editor
        if not isinstance(view, FloatValueStepSpinBox):
            raise AssertionError("translateXに値とstepのViewがありません")
        self._open_context_menu(row.name_label)
        widget = self._require_window().widget
        if (
            widget.step_settings_menu.menuAction()
            not in row.context_menu.actions()
        ):
            raise AssertionError("属性行の右クリックにStep設定がありません")
        if tuple(
            action.text() for action in widget.step_settings_menu.actions()
        ) != (
            "初期値に戻す: 全ての属性",
            "初期値に戻す: 選択属性",
        ):
            raise AssertionError("Step設定のリセット順または表記が不正です")
        row.context_menu.close()
        cmds.flushUndo()
        self._key(view.step_spin_box, qt.Qt.Key.Key_Down)
        if view.singleStep() != 0.1:
            raise AssertionError("stepの桁変更が反映されません")
        if (
            widget.step_profile.single_step("translate.translateX", "distance")
            != 0.1
        ):
            raise AssertionError("stepの変更がprofileへ反映されません")
        self._assert_values("translateX", (0, 0))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("step変更でUndo履歴が増えました")
        self._key(view.spin_box, qt.Qt.Key.Key_Up)
        self._assert_values("translateX", (0.1, 0.1))
        self.steps.append("step_field_changes_only_increment")

    def _undo_step_value(self) -> None:
        """値だけをUndoし、再構築後もユーザーのstepを保持する。"""
        from maya import cmds

        from bd_util.ui import FloatValueStepSpinBox

        cmds.undo()
        self._flush_gui()
        self._assert_values("translateX", (0, 0))
        view = self._row("translate.translateX").editor
        if (
            not isinstance(view, FloatValueStepSpinBox)
            or view.singleStep() != 0.1
        ):
            raise AssertionError("Undoでstep設定が失われました")
        self.steps.append("undo_value_preserves_step")

    def _edit_bool(self) -> None:
        """CheckBoxのSpace操作で複数ノードを同じ値へ変更する。"""
        from maya import cmds

        from bd_util.ui import BoolCheckBox, qt

        row = self._row("enabled")
        if (
            not isinstance(row.editor, BoolCheckBox)
            or not row.row.binding.is_mixed
        ):
            raise AssertionError("bool行に初期値の混在が表示されていません")
        cmds.flushUndo()
        self._key(row.editor, qt.Qt.Key.Key_Space)
        self._assert_values("enabled", (True, True))
        self.steps.append("checkbox_key_edit_multiple_nodes")

    def _undo_bool(self) -> None:
        """boolの一括変更が1回のUndoで戻ることを確認する。"""
        from maya import cmds

        cmds.undo()
        self._assert_values("enabled", (False, True))
        self.steps.append("undo_bool_once")

    def _inspect_enum_popup(self) -> None:
        """混在したenumの代表値を表示し、選択肢を開いた状態を描画する。"""
        from maya import cmds

        from bd_util.ui import EnumComboBox

        view = self._row("mode").editor
        if (
            not isinstance(view, EnumComboBox)
            or view.currentText() != "Preview"
        ):
            raise AssertionError("enumの代表項目が表示されません")
        self._assert_values("mode", (5, -2))
        cmds.flushUndo()
        view.showPopup()
        self._flush_gui()
        if not view.view().isVisible():
            raise AssertionError("enumの選択肢を開けません")
        popup_path = self.output / "08-enum-popup.png"
        if not view.view().window().grab().save(str(popup_path)):
            raise RuntimeError("enumの選択肢画像を保存できません")
        self.screenshots.append(str(popup_path))
        self.steps.append("enum_popup_preserves_mixed_values")

    def _select_enum_item(self) -> None:
        """開いた選択肢をマウスで選び、飛び番の実値を一括適用する。"""
        from bd_util.ui import EnumComboBox, qt

        view = self._row("mode").editor
        if not isinstance(view, EnumComboBox):
            raise AssertionError("enumのComboBoxがありません")
        popup = view.view()
        index = view.model().index(3, 0)
        position = popup.visualRect(index).center()
        for event_type in (
            qt.QEvent.Type.MouseButtonPress,
            qt.QEvent.Type.MouseButtonRelease,
        ):
            self._mouse(popup.viewport(), event_type, position)
        self._flush_gui()
        self._assert_values("mode", (10, 10))
        if view.currentText() != "Final":
            raise AssertionError("選択したenum項目が表示されません")
        self._capture("09-enum-selected.png")
        self.steps.append("enum_popup_mouse_selection_applies_sparse_value")

    def _undo_enum(self) -> None:
        """enumの一括選択を一回のUndoで各ノードの元値へ戻す。"""
        from maya import cmds

        cmds.undo()
        self._flush_gui()
        self._assert_values("mode", (5, -2))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("enum入力が一回のUndoにまとまりません")
        self.steps.append("undo_enum_restores_mixed_values")

    def _align_enum(self) -> None:
        """属性メニューから、enumの代表項目へ明示的に揃える。"""
        from bd_util.ui import qt

        row = self._row("mode")
        self._open_context_menu(row.name_label)
        row.context_menu.setActiveAction(row.align_action)
        self._key(row.context_menu, qt.Qt.Key.Key_Return)
        self._flush_gui()
        self._assert_values("mode", (5, 5))
        self.steps.append("enum_context_alignment")

    def _undo_enum_alignment(self) -> None:
        """enumの揃える操作をUndoし、後続の検証へ元値を引き継ぐ。"""
        from maya import cmds

        cmds.undo()
        self._flush_gui()
        self._assert_values("mode", (5, -2))
        self.steps.append("undo_enum_alignment")

    def _edit_float(self) -> None:
        """SpinBoxへ文字を入力して複数ノードの数値を確定する。"""
        from maya import cmds

        from bd_util.ui import FloatSliderSpinBox, qt

        row = self._row("weight")
        if not isinstance(row.editor, FloatSliderSpinBox):
            raise AssertionError("weight行にSlider付きViewがありません")
        cmds.flushUndo()
        editor = row.editor.spin_box
        self._key(
            editor,
            qt.Qt.Key.Key_A,
            modifiers=qt.Qt.KeyboardModifier.ControlModifier,
        )
        for character in "0.6":
            self._key(editor, ord(character), text=character)
        self._key(editor, qt.Qt.Key.Key_Return)
        self._assert_values("weight", (0.6, 0.6))
        self.steps.append("spinbox_keyboard_edit_multiple_nodes")

    def _undo_float(self) -> None:
        """数値の一括入力が1回のUndoで戻ることを確認する。"""
        from maya import cmds

        cmds.undo()
        self._assert_values("weight", (0.25, 0.75))
        self.steps.append("undo_float_once")

    def _drag_float(self) -> None:
        """Sliderのハンドルをマウスイベントで連続移動する。"""
        from maya import cmds

        from bd_util.ui import FloatSliderSpinBox, qt

        row = self._row("weight")
        if not isinstance(row.editor, FloatSliderSpinBox):
            raise AssertionError("weight行にSlider付きViewがありません")
        slider = row.editor.slider
        self._require_window().widget.scroll_area.ensureWidgetVisible(slider)
        option = qt.QtWidgets.QStyleOptionSlider()
        slider.initStyleOption(option)
        style = slider.style()
        if style is None:
            raise AssertionError("Sliderの描画styleを取得できません")
        handle = style.subControlRect(
            qt.QtWidgets.QStyle.ComplexControl.CC_Slider,
            option,
            qt.QtWidgets.QStyle.SubControl.SC_SliderHandle,
            slider,
        )
        start = handle.center()
        cmds.flushUndo()
        self._mouse(slider, qt.QEvent.Type.MouseButtonPress, start)
        for distance in (10, 20, 40):
            self._mouse(
                slider,
                qt.QEvent.Type.MouseMove,
                start + qt.QPoint(distance, 0),
            )
        self._mouse(
            slider, qt.QEvent.Type.MouseButtonRelease, start + qt.QPoint(40, 0)
        )
        values = tuple(cmds.getAttr(f"{node}.weight") for node in self.nodes)
        if abs(values[0] - values[1]) > 1e-8 or abs(values[0] - 0.25) < 1e-8:
            raise AssertionError(
                f"Slider操作が両ノードへ反映されていません: {values}"
            )
        self.steps.append("slider_mouse_drag_multiple_nodes")

    def _undo_drag(self) -> None:
        """Sliderの連続操作全体が1回のUndoで戻ることを確認する。"""
        from maya import cmds

        cmds.undo()
        self._assert_values("weight", (0.25, 0.75))
        self.steps.append("undo_slider_drag_once")

    def _align_bool(self) -> None:
        """属性名の右クリックメニューから、代表値と同じboolへ揃える。"""
        from maya import cmds

        from bd_util.ui import qt

        row = self._row("enabled")
        if not row.align_action.isEnabled():
            raise AssertionError("混在値を揃える操作が無効になっています")
        cmds.flushUndo()
        self._open_context_menu(row.name_label)
        if not row.context_menu.isVisible():
            raise AssertionError("混在行のメニューを開けません")
        image_path = self.output / "04-attribute-menu.png"
        if not row.context_menu.grab().save(str(image_path)):
            raise RuntimeError("属性行のメニュー画像を保存できません")
        self.screenshots.append(str(image_path))
        row.context_menu.setActiveAction(row.align_action)
        self._key(row.context_menu, qt.Qt.Key.Key_Return)
        self._assert_values("enabled", (False, False))
        self.steps.append("align_representative_bool_value")

    def _undo_alignment(self) -> None:
        """代表値へ揃える操作が1回のUndoで戻ることを確認する。"""
        from maya import cmds

        cmds.undo()
        self._assert_values("enabled", (False, True))
        self.steps.append("undo_alignment_once")

    def _show_state_mode(self) -> None:
        """表示モードを実UIで切り替え、無書込みと必要時のスクロールを確認する。"""
        from maya import cmds

        window = self._require_window()
        widget = window.widget
        self._flush_gui()
        row = self._row("enabled")
        self._value_layout = self._row_layout(row)
        if widget.scroll_area.verticalScrollBar().isVisible():
            raise AssertionError(
                "値行が収まる高さでも縦スクロールバーが残ります"
            )
        self.measurements["value_mode_rows"] = len(widget.row_widgets)
        if any(
            item.row.attribute.path == "hiddenWeight"
            for item in widget.row_widgets
        ):
            raise AssertionError("値モードにHide属性が表示されています")
        self._capture("10-values-before-mode-switch.png")
        before = self._attribute_states("enabled")
        cmds.flushUndo()
        self._select_combo_item(widget.mode_combo, 1)
        state_row = self._state_row("enabled")
        self._assert_state_layout(state_row)
        if not widget.scroll_area.verticalScrollBar().isVisible():
            raise AssertionError(
                "全属性の設定表示で縦スクロールバーが出ません"
            )
        self._state_row("hiddenWeight")
        self.measurements["state_mode_rows"] = len(widget.row_widgets)
        if (
            self.measurements["state_mode_rows"]
            <= self.measurements["value_mode_rows"]
        ):
            raise AssertionError("状態モードで非表示属性の行が増えません")
        if self._attribute_states("enabled") != before:
            raise AssertionError("モード切替で属性の状態が変わりました")
        self._assert_values("hiddenWeight", (0.2, 0.6))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("モード切替でUndo履歴が増えました")
        self._capture("11-state-mode-hidden-attributes.png")
        self.steps.append("mode_switch_preserves_scene_and_scrolls_as_needed")

    def _edit_display_state(self) -> None:
        """非表示属性を3状態へ切り替え、行の維持とUndo/Redoを確認する。"""
        from maya import cmds

        initial = ((False, False, False),) * len(self.nodes)
        for mode, expected in (
            ("channel_box", (False, True, False)),
            ("keyable", (True, False, False)),
        ):
            cmds.flushUndo()
            row = self._state_row("hiddenWeight")
            self._select_radio_button(row.display_buttons[mode])
            if self._attribute_states("hiddenWeight") != (expected,) * 2:
                raise AssertionError(f"非表示属性を{mode}へ変更できません")
            self._assert_values("hiddenWeight", (0.2, 0.6))
            cmds.undo()
            self._flush_gui()
            self._state_row("hiddenWeight")
            if self._attribute_states("hiddenWeight") != initial:
                raise AssertionError("表示状態をUndoで復元できません")
            if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                raise AssertionError("表示状態変更が1回のUndoになりません")
            cmds.redo()
            self._flush_gui()
            if self._attribute_states("hiddenWeight") != (expected,) * 2:
                raise AssertionError("表示状態をRedoで再適用できません")
            cmds.undo()
            self._flush_gui()

        # 表示されていた属性を隠しても設定行は維持する
        cmds.flushUndo()
        row = self._state_row("enabled")
        self._select_radio_button(row.display_buttons["hidden"])
        self._state_row("enabled")
        if self._attribute_states("enabled") != initial:
            raise AssertionError("Hideの設定または状態行の維持に失敗しました")
        cmds.undo()
        self._flush_gui()
        if self._attribute_states("enabled") != ((True, False, False),) * 2:
            raise AssertionError("Hide操作前の状態へ戻りません")
        self.steps.append("hidden_attribute_display_states_undo_redo")

    def _edit_lock_state(self) -> None:
        """ロックと解除を実入力で行い、表示状態と値を維持する。"""
        from maya import cmds

        from bd_util.ui import qt

        cmds.flushUndo()
        self._key(
            self._state_row("enabled").lock_check_box, qt.Qt.Key.Key_Space
        )
        self._flush_gui()
        if self._attribute_states("enabled") != ((True, False, True),) * 2:
            raise AssertionError("複数対象をロックできません")
        self._capture("12-state-mode-locked.png")
        cmds.undo()
        self._flush_gui()
        if self._attribute_states("enabled") != ((True, False, False),) * 2:
            raise AssertionError("ロック操作をUndoで戻せません")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("ロック変更が1回のUndoになりません")
        cmds.redo()
        self._flush_gui()
        self._key(
            self._state_row("enabled").lock_check_box, qt.Qt.Key.Key_Space
        )
        self._flush_gui()
        if self._attribute_states("enabled") != ((True, False, False),) * 2:
            raise AssertionError("ロック中の属性を解除できません")
        self._assert_values("enabled", (False, True))
        self.steps.append("lock_unlock_preserves_visibility_and_values")

    def _inspect_mixed_states(self) -> None:
        """外部から作った混在を表示し、明示操作だけで各状態を揃える。"""
        from maya import cmds

        from bd_util.ui import qt

        cmds.setAttr(
            f"{self.nodes[1]}.enabled", keyable=False, channelBox=True
        )
        cmds.setAttr(f"{self.nodes[1]}.enabled", lock=True)
        self._flush_gui()
        row = self._state_row("enabled")
        if (
            row.lock_check_box.checkState()
            != qt.Qt.CheckState.PartiallyChecked
        ):
            raise AssertionError("ロックの混在が三状態で表示されません")
        if any(button.isChecked() for button in row.display_buttons.values()):
            raise AssertionError("混在時に表示状態が未選択になっていません")
        if "混在" not in row.display_buttons["keyable"].toolTip():
            raise AssertionError("表示状態の混在が説明されません")
        initial = self._attribute_states("enabled")
        self._capture("13-state-mode-mixed.png")
        cmds.flushUndo()
        self._key(row.display_buttons["keyable"], qt.Qt.Key.Key_Space)
        self._flush_gui()
        if self._attribute_states("enabled") != (
            (True, False, False),
            (True, False, True),
        ):
            raise AssertionError("表示状態の変更がロックを維持しません")
        self._key(
            self._state_row("enabled").lock_check_box, qt.Qt.Key.Key_Space
        )
        self._flush_gui()
        if self._attribute_states("enabled") != ((True, False, True),) * 2:
            raise AssertionError("混在ロックを明示入力で揃えられません")
        cmds.undo()
        self._flush_gui()
        cmds.undo()
        self._flush_gui()
        if self._attribute_states("enabled") != initial:
            raise AssertionError("各状態のUndoで元の混在へ戻りません")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("表示とロックが独立したUndoになりません")

        # 後続の値モード確認へ最初の表示状態を引き継ぐ
        cmds.setAttr(f"{self.nodes[1]}.enabled", lock=False)
        cmds.setAttr(
            f"{self.nodes[1]}.enabled", keyable=True, channelBox=False
        )
        self._flush_gui()
        self.steps.append("mixed_visibility_and_lock_edit_independently")

    def _return_to_values(self) -> None:
        """値モードへ戻し、列位置・値・刻み幅の維持を確認する。"""
        from maya import cmds

        from bd_util.ui import FloatValueStepSpinBox

        widget = self._require_window().widget
        cmds.flushUndo()
        self._select_combo_item(widget.mode_combo, 0)
        if self._row_layout(self._row("enabled")) != self._value_layout:
            raise AssertionError(
                "値モードへ戻した際に横幅か列位置が変わりました"
            )
        if any(
            item.row.attribute.path == "hiddenWeight"
            for item in widget.row_widgets
        ):
            raise AssertionError(
                "値モードへ戻してもHide属性の行が残っています"
            )
        view = self._row("translate.translateX").editor
        if (
            not isinstance(view, FloatValueStepSpinBox)
            or view.singleStep() != 0.1
        ):
            raise AssertionError("モード切替でstep設定が失われました")
        self._assert_values("enabled", (False, True))
        self._assert_values("weight", (0.25, 0.75))
        self._assert_values("mode", (5, -2))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("値モードへの切替でUndo履歴が増えました")
        self._capture("14-values-after-mode-switch.png")
        self.steps.append("return_to_values_preserves_width_step_and_scene")

    def _inspect_filters(self) -> None:
        """両モードの絞り込み、選択保持と状態操作後の行の出入りを実UIで確認する。"""
        from maya import cmds

        widget = self._require_window().widget
        custom = {"enabled", "weight", "mode", "modeCopy", "hiddenWeight"}
        initial = self._attribute_states("weight")
        cmds.flushUndo()
        for mode_index in (0, 1):
            self._select_combo_item(widget.mode_combo, mode_index)
            for value, expected in (
                ("all", custom),
                ("visible", custom - {"hiddenWeight"}),
                ("keyable", custom - {"hiddenWeight"}),
                ("channel_box", set()),
                ("hidden", {"hiddenWeight"}),
            ):
                self._select_combo_item(
                    widget.filter_combo, widget.filter_combo.findData(value)
                )
                actual = {
                    row.row.attribute.path for row in widget.row_widgets
                }.intersection(custom)
                if actual != expected:
                    raise AssertionError(
                        f"フィルター結果が異なります: {mode_index}/{value}: {actual}"
                    )
                if widget.scroll_area.horizontalScrollBar().maximum():
                    raise AssertionError(
                        "絞り込み後に横スクロールが発生しました"
                    )
            if mode_index == 0:
                self._row("hiddenWeight")
                self._capture("15-values-hidden-filter.png")
        self._select_combo_item(widget.mode_combo, 0)
        if widget.filter_combo.currentData() != "hidden":
            raise AssertionError("値モードのフィルターが保持されません")
        self._select_combo_item(widget.mode_combo, 1)
        if widget.filter_combo.currentData() != "hidden":
            raise AssertionError("状態モードのフィルターが保持されません")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("フィルター切替でUndo履歴が増えました")
        self._assert_values("hiddenWeight", (0.2, 0.6))
        self.steps.append("five_filters_in_both_modes_and_per_mode_memory")

        # 絞り込み対象から外れる操作でも、両ノードへの入力とUndoを完了する
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("keyable")
        )
        if widget.scroll_area.verticalScrollBar().isVisible():
            raise AssertionError(
                "設定行を絞り込んでも縦スクロールバーが残ります"
            )
        self._capture("16-states-keyable-filter.png")
        row = self._state_row("weight")
        self._select_radio_button(row.display_buttons["hidden"])
        if self._attribute_states("weight") != ((False, False, False),) * 2:
            raise AssertionError(
                "絞り込み中の表示変更が両対象へ反映されません"
            )
        if any(r.row.attribute.path == "weight" for r in widget.row_widgets):
            raise AssertionError("条件から外れた行が表示に残っています")
        cmds.undo()
        self._flush_gui()
        self._state_row("weight")
        if self._attribute_states("weight") != initial:
            raise AssertionError("絞り込み中の表示変更をUndoできません")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("絞り込み中の表示変更が1回のUndoになりません")
        cmds.redo()
        self._flush_gui()
        if any(r.row.attribute.path == "weight" for r in widget.row_widgets):
            raise AssertionError("Redo後に行が再度絞り込まれません")
        cmds.undo()
        self._flush_gui()
        self.steps.append("filtered_state_edit_removal_undo_redo")

        # 後続のclose・reload確認へ既定の表示を引き継ぐ
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("all")
        )
        self._select_combo_item(widget.mode_combo, 0)
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("visible")
        )

    def _inspect_attribute_order(self) -> None:
        """jointの優先順を両モードの実画面で確認し、通常の選択へ戻す。"""
        from maya import cmds

        widget = self._require_window().widget
        joint = cmds.createNode("joint", name="bdChannelBoxOrderQA")
        cmds.select(joint, replace=True)
        self._flush_gui()
        expected = ["visibility"]
        for parent, children in (
            ("translate", "XYZ"),
            ("rotate", "XYZ"),
            ("scale", "XYZ"),
            ("jointOrient", "XYZ"),
            ("", ("rotateOrder",)),
            ("rotateAxis", "XYZ"),
            ("shear", ("XY", "XZ", "YZ")),
            ("rotatePivot", "XYZ"),
            ("rotatePivotTranslate", "XYZ"),
            ("scalePivot", "XYZ"),
            ("scalePivotTranslate", "XYZ"),
        ):
            expected.extend(
                f"{parent}.{parent}{child}" if parent else child
                for child in children
            )
        cmds.flushUndo()
        for mode_index in (0, 1):
            self._select_combo_item(widget.mode_combo, mode_index)
            self._select_combo_item(
                widget.filter_combo, widget.filter_combo.findData("all")
            )
            paths = [r.row.attribute.path for r in widget.row_widgets]
            if paths[:32] != expected:
                raise AssertionError(
                    f"jointの優先順が異なります: {paths[:32]}"
                )
            if paths[32:34] != [
                "drawOverride.overrideEnabled",
                "drawOverride.overrideDisplayType",
            ]:
                raise AssertionError(
                    "drawOverrideの先頭がoverrideEnabledになっていません"
                )
            widget.scroll_area.verticalScrollBar().setValue(0)
            self._flush_gui()
            self._capture(f"17-attribute-order-mode-{mode_index}.png")
            target = widget.row_widgets[32]
            widget.scroll_area.verticalScrollBar().setValue(target.y())
            self._flush_gui()
            self._capture(f"18-draw-override-mode-{mode_index}.png")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("表示順の確認でUndo履歴が増えました")
        self.steps.append("joint_priority_order_in_both_modes")

        # 検証用jointを除き、後続のclose・reload検証の選択と表示へ戻す
        cmds.select(self.nodes, replace=True)
        self._flush_gui()
        cmds.delete(joint)
        self._select_combo_item(widget.mode_combo, 0)
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("visible")
        )

    def _inspect_multi_attribute_selection(self) -> None:
        """実画面で六行を選択し、直接入力・選択メニュー・一Undoを確認する。"""
        from maya import cmds

        from bd_util.ui import FloatValueStepSpinBox, qt

        widget = self._require_window().widget
        attributes = tuple(
            f"{parent}{axis}"
            for parent in ("translate", "rotate")
            for axis in "XYZ"
        )
        keys = tuple(
            (f"{parent}.{parent}{axis}", kind)
            for parent, kind in (
                ("translate", "distance"),
                ("rotate", "angle"),
            )
            for axis in "XYZ"
        )
        before = {
            name: tuple(cmds.getAttr(f"{node}.{name}") for node in self.nodes)
            for name in attributes
        }
        first = self._row("translate.translateX").name_label
        last = self._row("rotate.rotateZ").name_label
        value_palettes: dict[str, tuple[qt.QtGui.QColor, qt.QtGui.QColor]] = {}
        for path, _kind in keys:
            editor = self._row(path).editor
            if not isinstance(editor, FloatValueStepSpinBox):
                raise AssertionError(f"数値の入力Viewがありません: {path}")
            palette = editor.spin_box.palette()
            value_palettes[path] = (
                palette.color(qt.QPalette.ColorRole.Base),
                palette.color(qt.QPalette.ColorRole.Text),
            )
        widget.table_view.ensureWidgetVisible(first)
        self._flush_gui()
        cmds.flushUndo()

        # 名前欄のドラッグを実際のtable選択として処理する
        self._mouse(
            first, qt.QEvent.Type.MouseButtonPress, first.rect().center()
        )
        end = first.mapFromGlobal(last.mapToGlobal(last.rect().center()))
        self._mouse(first, qt.QEvent.Type.MouseMove, end)
        self._mouse(first, qt.QEvent.Type.MouseButtonRelease, end)
        if widget.table_view.selected_keys() != keys:
            raise AssertionError("六属性のドラッグ選択に失敗しました")
        highlight = widget.table_view.palette().color(
            qt.QPalette.ColorRole.Highlight
        )
        for path, _kind in keys:
            row = self._row(path)
            if row.name_label.contentsMargins().right() != 4:
                raise AssertionError(f"属性名の右余白が不正です: {path}")
            if row.editor.x() != row.name_label.x() + row.name_label.width():
                raise AssertionError(
                    f"属性名と入力欄の間に隙間があります: {path}"
                )
            if (
                row.name_label.palette().color(qt.QPalette.ColorRole.Window)
                != highlight
            ):
                raise AssertionError(f"属性名へ選択色が付きません: {path}")
            editor = row.editor
            assert isinstance(editor, FloatValueStepSpinBox)
            palette = editor.spin_box.palette()
            current = (
                palette.color(qt.QPalette.ColorRole.Base),
                palette.color(qt.QPalette.ColorRole.Text),
            )
            if current != value_palettes[path]:
                raise AssertionError(f"値欄の配色が変わりました: {path}")
        self._capture("25-multi-attribute-selection.png")
        view = self._row("rotate.rotateZ").editor
        if not isinstance(view, FloatValueStepSpinBox):
            raise AssertionError("数値の入力Viewがありません")
        self._key(view.spin_box, qt.Qt.Key.Key_5, text="5")
        focused = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "focusWidget"),
        )()
        if (
            not isinstance(focused, qt.QLineEdit)
            or focused.objectName() != "channel_batch_numeric_editor"
        ):
            raise AssertionError("一括入力欄が開きません")
        for name in attributes:
            self._assert_values(name, before[name])
        self._capture("26-multi-attribute-typing.png")
        self._key(focused, qt.Qt.Key.Key_Return)
        self._flush_gui()
        for name in attributes:
            self._assert_values(name, (5.0, 5.0))
        self._capture("27-multi-attribute-applied.png")
        cmds.undo()
        self._flush_gui()
        for name in attributes:
            self._assert_values(name, before[name])
        if widget.table_view.selected_keys() != keys:
            raise AssertionError("Undoで属性選択が失われました")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("複数属性の数値入力が一Undoになっていません")

        # 選択内の右クリックから全属性をロックし、一回で復元する
        row = self._row("translate.translateX")
        self._open_context_menu(row.name_label)
        lock_action = next(
            action
            for action in row.context_menu.actions()
            if action.objectName() == "selected_lock"
        )
        row.context_menu.setActiveAction(lock_action)
        menu_path = self.output / "28-multi-attribute-menu.png"
        if not row.context_menu.grab().save(str(menu_path)):
            raise RuntimeError("選択属性メニューの画像を保存できません")
        self.screenshots.append(str(menu_path))
        self._key(row.context_menu, qt.Qt.Key.Key_Return)
        for node in self.nodes:
            for name in attributes:
                if not cmds.getAttr(f"{node}.{name}", lock=True):
                    raise AssertionError(
                        "選択メニューの一括ロックに失敗しました"
                    )
        cmds.undo()
        self._flush_gui()
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("複数属性のロックが一Undoになっていません")
        self.steps.append(
            "multi_attribute_selection_numeric_input_menu_and_undo"
        )

    def _inspect_multi_value_controls(self) -> None:
        """既存の上下・Slider・bool・enum入力を選択属性へ一括適用する。"""
        from maya import cmds

        from bd_util.ui import (
            BoolCheckBox,
            EnumComboBox,
            FloatSliderSpinBox,
            FloatValueStepSpinBox,
        )

        widget = self._require_window().widget

        # 操作元のStepによる共通増減量を六つの数値属性へ加える
        numeric_paths = (
            "translate.translateX",
            "translate.translateY",
            "translate.translateZ",
            "rotate.rotateX",
            "rotate.rotateY",
            "rotate.rotateZ",
        )
        numeric_keys = tuple(
            (
                self._row(path).row.attribute.path,
                self._row(path).row.attribute.kind,
            )
            for path in numeric_paths
        )
        numeric_before = {
            path: tuple(
                cmds.getAttr(f"{node}.{path.rsplit('.', 1)[-1]}")
                for node in self.nodes
            )
            for path in numeric_paths
        }
        widget.table_view.select_keys(numeric_keys)
        step_editor = self._row("translate.translateX").editor
        if not isinstance(step_editor, FloatValueStepSpinBox):
            raise AssertionError("translateXに値とStepのViewがありません")
        step_editor.setSingleStep(0.5)
        cmds.flushUndo()
        step_editor.spin_box.stepUp()
        self._flush_gui()
        for path in numeric_paths:
            name = path.rsplit(".", 1)[-1]
            expected = tuple(value + 0.5 for value in numeric_before[path])
            self._assert_values(name, expected)
        cmds.undo()
        self._flush_gui()
        for path in numeric_paths:
            self._assert_values(path.rsplit(".", 1)[-1], numeric_before[path])
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("複数属性の上下操作が一Undoになっていません")

        # Sliderの連続入力で、選択数値を同じ表示値へ揃える
        slider_row = self._row("weight")
        slider_editor = slider_row.editor
        if not isinstance(slider_editor, FloatSliderSpinBox):
            raise AssertionError("weight行にSlider付きViewがありません")
        slider_keys = tuple(
            (row.row.attribute.path, row.row.attribute.kind)
            for row in (slider_row, self._row("translate.translateX"))
        )
        widget.table_view.select_keys(slider_keys)
        cmds.flushUndo()
        slider_editor.slider.setSliderDown(True)
        slider_editor.slider.setValue(600)
        slider_editor.slider.setValue(700)
        slider_editor.slider.setSliderDown(False)
        self._flush_gui()
        self._assert_values("weight", (0.7, 0.7))
        self._assert_values("translateX", (0.7, 0.7))
        cmds.undo()
        self._flush_gui()
        self._assert_values("weight", (0.25, 0.75))
        self._assert_values(
            "translateX", numeric_before["translate.translateX"]
        )
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError(
                "複数属性のSlider操作が一Undoになっていません"
            )

        # boolと互換enumも、それぞれ操作した状態・項目へ揃える
        enabled_row = self._row("enabled")
        visibility_row = self._row("visibility")
        if not isinstance(enabled_row.editor, BoolCheckBox):
            raise AssertionError("enabled行にCheckBoxがありません")
        widget.table_view.select_keys(
            tuple(
                (row.row.attribute.path, row.row.attribute.kind)
                for row in (enabled_row, visibility_row)
            )
        )
        cmds.flushUndo()
        enabled_row.editor.click()
        self._flush_gui()
        self._assert_values("enabled", (True, True))
        self._assert_values("visibility", (True, True))
        cmds.undo()
        self._flush_gui()
        self._assert_values("enabled", (False, True))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("複数bool属性の入力が一Undoになっていません")

        mode_row = self._row("mode")
        copy_row = self._row("modeCopy")
        if not isinstance(mode_row.editor, EnumComboBox):
            raise AssertionError("mode行にComboBoxがありません")
        widget.table_view.select_keys(
            tuple(
                (row.row.attribute.path, row.row.attribute.kind)
                for row in (mode_row, copy_row)
            )
        )
        cmds.flushUndo()
        self._select_combo_item(mode_row.editor, 3)
        self._assert_values("mode", (10, 10))
        self._assert_values("modeCopy", (10, 10))
        cmds.undo()
        self._flush_gui()
        self._assert_values("mode", (5, -2))
        self._assert_values("modeCopy", (0, 10))
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("複数enum属性の入力が一Undoになっていません")
        self._capture("29-multi-attribute-value-controls.png")
        self.steps.append("multi_attribute_value_controls_and_undo")

    def _inspect_multi_state_controls(self) -> None:
        """表示・lockの直接入力を選択属性へ一括適用する。"""
        from maya import cmds

        from bd_util.ui import qt

        widget = self._require_window().widget
        self._select_combo_item(widget.mode_combo, 1)
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("all")
        )
        paths = ("translate.translateX", "translate.translateY")
        rows = tuple(self._state_row(path) for path in paths)
        selected = tuple(
            (row.row.attribute.path, row.row.attribute.kind) for row in rows
        )
        widget.table_view.select_keys(selected)

        # 選択行の表示ボタンから、全属性をHideへ揃える
        cmds.flushUndo()
        self._select_radio_button(rows[0].display_buttons["hidden"])
        for name in ("translateX", "translateY"):
            if self._attribute_states(name) != (
                (False, False, False),
                (False, False, False),
            ):
                raise AssertionError(
                    f"選択属性のHide一括操作に失敗しました: {name}"
                )
        self._capture("34-multi-attribute-display-state.png")
        cmds.undo()
        self._flush_gui()
        for name in ("translateX", "translateY"):
            if self._attribute_states(name) != (
                (True, False, False),
                (True, False, False),
            ):
                raise AssertionError("Hide一括操作をUndoで戻せません")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("Hide一括操作が一Undoになっていません")

        # lockのSpace入力も選択属性へ適用する
        rows = tuple(self._state_row(path) for path in paths)
        widget.table_view.select_keys(selected)
        cmds.flushUndo()
        self._key(rows[0].lock_check_box, qt.Qt.Key.Key_Space)
        self._flush_gui()
        for name in ("translateX", "translateY"):
            if self._attribute_states(name) != (
                (True, False, True),
                (True, False, True),
            ):
                raise AssertionError("lockの選択属性操作に失敗しました")
        self._capture("35-multi-attribute-lock-state.png")
        cmds.undo()
        self._flush_gui()
        for name in ("translateX", "translateY"):
            if self._attribute_states(name) != (
                (True, False, False),
                (True, False, False),
            ):
                raise AssertionError("lock一括操作をUndoで戻せません")
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("lock一括操作が一Undoになっていません")

        self._select_combo_item(widget.mode_combo, 0)
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("visible")
        )
        self.steps.append("multi_attribute_state_controls_and_undo")

    def _inspect_clipboard_value_transfer(self) -> None:
        """実メニューのCopyと表示条件を含むPaste規則を一Undoまで確認する。"""
        from maya import cmds

        from bd_util.maya.ui import MayaScalarValueClipboard
        from bd_util.ui import qt

        widget = self._require_window().widget
        clipboard = qt.QApplication.clipboard()
        saved = qt.QtCore.QMimeData()
        original_mime = clipboard.mimeData()
        serialized_mime: list[dict[str, str]] = []
        for mime_type in original_mime.formats():
            data = original_mime.data(mime_type)
            saved.setData(mime_type, data)
            serialized_mime.append(
                {
                    "format": mime_type,
                    "data": base64.b64encode(bytes(data)).decode("ascii"),
                }
            )
        original_values = {
            name: tuple(cmds.getAttr(f"{node}.{name}") for node in self.nodes)
            for name in (
                "translateX",
                "translateY",
                "translateZ",
                "weight",
                "enabled",
                "mode",
            )
        }
        original_display_states = {
            f"{node}.{name}": (
                bool(cmds.getAttr(f"{node}.{name}", keyable=True)),
                bool(cmds.getAttr(f"{node}.{name}", channelBox=True)),
            )
            for node in self.nodes
            for name in ("weight", "enabled", "mode")
        }
        try:
            # 選択した一属性だけをCopyし、異なる同型pathへ展開する
            cmds.setAttr(f"{self.nodes[0]}.translateX", 4.25)
            source = self._row("translate.translateX")
            widget.table_view.select_keys(
                ((source.row.attribute.path, source.row.attribute.kind),)
            )
            cmds.flushUndo()
            self._open_context_menu(source.name_label)
            copy_selected = source.copy_selected_values_action
            if not copy_selected.isEnabled():
                raise AssertionError("選択属性のCopyが有効になりません")
            copy_selected.trigger()
            source.context_menu.close()
            targets = tuple(
                self._row(path)
                for path in (
                    "translate.translateY",
                    "translate.translateZ",
                )
            )
            widget.table_view.select_keys(
                tuple(
                    (row.row.attribute.path, row.row.attribute.kind)
                    for row in targets
                )
            )
            target = targets[0]
            self._open_context_menu(target.name_label)
            selected_paste = target.paste_selected_values_action
            if not selected_paste.isEnabled():
                raise AssertionError(
                    "一つのコピー値を選択属性へ貼る操作が有効になりません"
                )
            target.paste_menu.popup(
                target.name_label.mapToGlobal(
                    qt.QPoint(target.name_label.width(), 0)
                )
            )
            self._flush_gui()
            menu_path = self.output / "32-clipboard-value-menu.png"
            if not target.paste_menu.grab().save(str(menu_path)):
                raise RuntimeError(
                    "一値を選択属性へ貼るメニュー画像を保存できません"
                )
            self.screenshots.append(str(menu_path))
            selected_paste.trigger()
            target.paste_menu.close()
            target.context_menu.close()
            self._flush_gui()
            self._assert_values(
                "translateX", (4.25, original_values["translateX"][1])
            )
            self._assert_values("translateY", (4.25, 4.25))
            self._assert_values("translateZ", (4.25, 4.25))
            if widget.message_label.isVisible() or widget.message_label.text():
                raise AssertionError("選択属性Paste後に操作通知が残っています")
            cmds.undo()
            self._flush_gui()
            self._assert_values(
                "translateX", (4.25, original_values["translateX"][1])
            )
            self._assert_values("translateY", original_values["translateY"])
            self._assert_values("translateZ", original_values["translateZ"])
            if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                raise AssertionError(
                    "一値から選択属性へのPasteが一回のUndoになっていません"
                )

            # 選択属性だけをCopyし、Copy元と同じpathへ貼り付ける
            rows = tuple(
                self._row(path) for path in ("weight", "enabled", "mode")
            )
            widget.table_view.select_keys(
                tuple(
                    (row.row.attribute.path, row.row.attribute.kind)
                    for row in rows
                )
            )
            cmds.flushUndo()
            widget.edit_menu.aboutToShow.emit()
            if not widget.copy_selected_values_action.isEnabled():
                raise AssertionError("選択属性のCopyが有効になりません")
            widget.copy_selected_values_action.trigger()
            transfer = MayaScalarValueClipboard().read()
            copied = {
                snapshot.path: snapshot.value
                for snapshot in transfer.nodes[0].values
            }
            expected = {"weight": 0.25, "enabled": False, "mode": 5}
            if any(
                copied.get(path) != value for path, value in expected.items()
            ):
                raise AssertionError(f"選択属性のCopy値が不正です: {copied}")
            if len(copied) != len(expected):
                raise AssertionError("選択外の属性までCopyされています")
            if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                raise AssertionError("CopyでUndo履歴が増えました")

            # Copy後のsceneを変え、snapshot値が全選択nodeへ貼られることを確認する
            for node in self.nodes:
                cmds.setAttr(f"{node}.weight", 0.9)
                cmds.setAttr(f"{node}.enabled", True)
                cmds.setAttr(f"{node}.mode", 10)
            cmds.flushUndo()
            target_row = self._row("translate.translateX")
            widget.table_view.select_keys(
                (
                    (
                        target_row.row.attribute.path,
                        target_row.row.attribute.kind,
                    ),
                )
            )
            self._open_context_menu(target_row.name_label)
            paste_action = target_row.paste_copied_values_action
            if not paste_action.isEnabled():
                raise AssertionError("対応clipboardのPasteが有効になりません")
            paste_action.trigger()
            target_row.context_menu.close()
            self._flush_gui()
            self._assert_values("weight", (0.25, 0.25))
            self._assert_values("enabled", (False, False))
            self._assert_values("mode", (5, 5))
            if widget.message_label.isVisible() or widget.message_label.text():
                raise AssertionError("同path Paste後に操作通知が残っています")

            # 貼り付け後の全属性CopyをMaya再起動後のOS clipboard検証へ残す
            widget.edit_menu.aboutToShow.emit()
            if not widget.copy_all_values_action.isEnabled():
                raise AssertionError(
                    "基準nodeの全属性値Copyが有効になりません"
                )
            widget.copy_all_values_action.trigger()
            copied = {
                snapshot.path: snapshot.value
                for snapshot in MayaScalarValueClipboard()
                .read()
                .nodes[0]
                .values
            }
            if len(copied) <= len(expected):
                raise AssertionError("全対応属性がCopyされていません")
            cmds.undo()
            self._flush_gui()
            self._assert_values("weight", (0.9, 0.9))
            self._assert_values("enabled", (True, True))
            self._assert_values("mode", (10, 10))
            if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                raise AssertionError("Pasteが一回のUndoになっていません")

            # 基準nodeの表示状態でpathを決め、後続nodeにも同じpathを貼る
            cmds.setAttr(f"{self.nodes[0]}.weight", keyable=True)
            cmds.setAttr(f"{self.nodes[0]}.enabled", keyable=False)
            cmds.setAttr(f"{self.nodes[0]}.enabled", channelBox=True)
            cmds.setAttr(f"{self.nodes[0]}.mode", keyable=False)
            cmds.setAttr(f"{self.nodes[0]}.mode", channelBox=False)
            cmds.setAttr(f"{self.nodes[1]}.weight", keyable=False)
            cmds.setAttr(f"{self.nodes[1]}.weight", channelBox=False)
            cmds.setAttr(f"{self.nodes[1]}.enabled", keyable=False)
            cmds.setAttr(f"{self.nodes[1]}.enabled", channelBox=False)
            cmds.setAttr(f"{self.nodes[1]}.mode", keyable=True)
            self._flush_gui()
            target_row = self._row("translate.translateX")
            self._open_context_menu(target_row.name_label)
            expected_labels = (
                "全て",
                "keyable + channelbox",
                "keyable",
                "channelbox",
                "hide",
            )
            actual_labels = tuple(
                action.text()
                for action in target_row.paste_copied_values_actions.values()
            )
            if actual_labels != expected_labels:
                raise AssertionError(
                    f"表示状態Pasteメニューが不正です: {actual_labels}"
                )
            target_row.paste_copied_values_menu.popup(
                target_row.name_label.mapToGlobal(
                    qt.QPoint(target_row.name_label.width(), 0)
                )
            )
            self._flush_gui()
            filter_menu_path = self.output / "33-clipboard-filter-menu.png"
            if not target_row.paste_copied_values_menu.grab().save(
                str(filter_menu_path)
            ):
                raise RuntimeError(
                    "表示状態でPaste対象を選ぶメニュー画像を保存できません"
                )
            self.screenshots.append(str(filter_menu_path))
            cmds.flushUndo()
            target_row.paste_copied_values_actions["channel_box"].trigger()
            target_row.paste_copied_values_menu.close()
            target_row.paste_menu.close()
            target_row.context_menu.close()
            self._flush_gui()
            self._assert_values("weight", (0.9, 0.9))
            self._assert_values("enabled", (False, False))
            self._assert_values("mode", (10, 10))
            if widget.message_label.isVisible() or widget.message_label.text():
                raise AssertionError("表示状態Paste後に操作通知が残っています")
            cmds.undo()
            self._flush_gui()
            self._assert_values("enabled", (True, True))
            if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                raise AssertionError(
                    "表示状態Pasteが一回のUndoになっていません"
                )
        finally:
            if os.environ.get(_PREPARE_RESTART_VARIABLE) == "1":
                _write_json(
                    self.output / "clipboard-original.json",
                    serialized_mime,
                )
            else:
                clipboard.setMimeData(saved)
            for name, values in original_values.items():
                for node, value in zip(self.nodes, values, strict=True):
                    cmds.setAttr(f"{node}.{name}", value)
            for path, state in original_display_states.items():
                cmds.setAttr(path, keyable=state[0])
                cmds.setAttr(path, channelBox=state[1])
            cmds.flushUndo()
            self._flush_gui()
        self.steps.append("clipboard_copy_and_filtered_paste_modes")

    def _inspect_state_sweep(self) -> None:
        """実画面で三行をなぞり、即時反映、絞り込み保留と一回Undoを確認する。"""
        from maya import cmds

        from bd_util.ui import qt

        widget = self._require_window().widget
        self._select_combo_item(widget.mode_combo, 1)
        self._select_combo_item(
            widget.filter_combo, widget.filter_combo.findData("keyable")
        )
        first = self._state_row("translate.translateX").display_buttons[
            "hidden"
        ]
        last = self._state_row("translate.translateZ").display_buttons[
            "hidden"
        ]
        self._flush_gui()
        rows = widget.row_widgets
        start = qt.QPoint(8, first.height() // 2)
        end = first.mapFromGlobal(
            last.mapToGlobal(qt.QPoint(8, last.height() // 2))
        )
        cmds.flushUndo()
        self._mouse(first, qt.QEvent.Type.MouseButtonPress, start)
        self._mouse(first, qt.QEvent.Type.MouseMove, end)
        self._flush_gui()
        if not widget.state_sweep.is_active or widget.row_widgets != rows:
            raise AssertionError(
                "なぞり中に操作が終了、または行が再構築されました"
            )
        for attribute in ("translateX", "translateY", "translateZ"):
            if (
                self._attribute_states(attribute)
                != ((False, False, False),) * 2
            ):
                raise AssertionError(
                    f"途中の行を含む状態変更に失敗: {attribute}"
                )
        self._capture("19-state-sweep-during-drag.png")
        self._mouse(first, qt.QEvent.Type.MouseButtonRelease, end)
        self._flush_gui()
        if widget.state_sweep.is_active or any(
            row.row.attribute.name.startswith("translate")
            for row in widget.row_widgets
        ):
            raise AssertionError("なぞり終了後の絞り込みが反映されません")
        self._capture("20-state-sweep-after-release.png")
        cmds.undo()
        self._flush_gui()
        for attribute in ("translateX", "translateY", "translateZ"):
            if (
                self._attribute_states(attribute)
                != ((True, False, False),) * 2
            ):
                raise AssertionError(
                    f"一回のUndoで元に戻りません: {attribute}"
                )
        if not cmds.undoInfo(query=True, undoQueueEmpty=True):
            raise AssertionError("なぞり操作が複数のUndoに分かれています")
        cmds.redo()
        self._flush_gui()
        for attribute in ("translateX", "translateY", "translateZ"):
            if (
                self._attribute_states(attribute)
                != ((False, False, False),) * 2
            ):
                raise AssertionError(
                    f"一回のRedoで再適用できません: {attribute}"
                )
        cmds.undo()
        self._flush_gui()
        self.steps.append("radio_sweep_filter_deferral_and_single_undo_redo")
        self._select_combo_item(widget.mode_combo, 0)

    def _inspect_lock_sweep(self) -> None:
        """実画面でlock列を往復し、複数行のロック・解除とUndoを確認する。"""
        from maya import cmds

        from bd_util.ui import qt

        widget = self._require_window().widget
        self._select_combo_item(widget.mode_combo, 1)
        for locked in (True, False):
            first = self._state_row("translate.translateX").lock_check_box
            last = self._state_row("translate.translateZ").lock_check_box
            start = qt.QPoint(8, first.height() // 2)
            end = first.mapFromGlobal(
                last.mapToGlobal(qt.QPoint(8, last.height() // 2))
            )
            cmds.flushUndo()
            self._mouse(first, qt.QEvent.Type.MouseButtonPress, start)
            self._mouse(first, qt.QEvent.Type.MouseMove, end)
            self._mouse(first, qt.QEvent.Type.MouseMove, start)
            self._flush_gui()
            if not widget.lock_sweep.is_active:
                raise AssertionError("lockなぞりが途中で終了しました")
            for attribute in ("translateX", "translateY", "translateZ"):
                if (
                    self._attribute_states(attribute)
                    != ((True, False, locked),) * 2
                ):
                    raise AssertionError(
                        f"lockなぞりの反映に失敗: {attribute}"
                    )
            self._capture(f"21-lock-sweep-{locked}.png")
            self._mouse(first, qt.QEvent.Type.MouseButtonRelease, start)
            if widget.controller.state_edit_session.is_editing:
                raise AssertionError("lockなぞりのUndoが終了していません")
            cmds.undo()
            self._flush_gui()
            for attribute in ("translateX", "translateY", "translateZ"):
                if (
                    self._attribute_states(attribute)
                    != ((True, False, not locked),) * 2
                ):
                    raise AssertionError(f"lockの一回Undoに失敗: {attribute}")
            if not cmds.undoInfo(query=True, undoQueueEmpty=True):
                raise AssertionError("lockなぞりが複数のUndoに分かれています")
            cmds.redo()
            self._flush_gui()
            for attribute in ("translateX", "translateY", "translateZ"):
                if (
                    self._attribute_states(attribute)
                    != ((True, False, locked),) * 2
                ):
                    raise AssertionError(f"lockの一回Redoに失敗: {attribute}")
        self.steps.append("lock_sweep_round_trip_and_single_undo_redo")
        self._select_combo_item(widget.mode_combo, 0)

    def _close(self) -> None:
        """Maya側のclose操作からworkspaceControlごと完全破棄する。"""
        from maya import cmds
        from bd_tools import bd_channel_box

        cmds.workspaceControl(
            bd_channel_box.WORKSPACE_CONTROL_NAME, edit=True, close=True
        )
        self.steps.append("close")

    def _reopen(self) -> None:
        """close後のcallback解放を確認し、新しいWindowを表示する。"""
        from bd_tools import bd_channel_box
        from bd_util.ui import FloatValueStepSpinBox, qt

        if self.window is not None and qt.isValid(self.window):
            raise AssertionError("close後にWindowが破棄されていません")
        if self._callback_counts() != self.baseline_callbacks:
            raise AssertionError("close後にnode callbackが残っています")
        self.window = bd_channel_box.show()
        self._flush_gui()
        if self.window.widget.wheel_editing_action.isChecked():
            raise AssertionError("再表示後にホイール編集設定を復元できません")
        step = self._row("translate.translateX").editor
        if (
            not isinstance(step, FloatValueStepSpinBox)
            or step.singleStep() != _PERSISTED_STEP
        ):
            raise AssertionError("再表示後に属性Stepを復元できません")
        self.steps.append("reopen_without_callback_leak")

    def _change_selection(self) -> None:
        """異なる選択へ切り替えて追従処理を実行する。"""
        from maya import cmds

        cmds.select(self.nodes[1], replace=True)
        self.steps.append("change_selection")

    def _close_for_reload(self) -> None:
        """選択追従を確認し、標準Mayaだけのcallback基準値を取り直す。"""
        from bd_tools import bd_channel_box

        window = self._require_window()
        names = window.widget.controller.node_names
        if len(names) != 1 or names[0].rsplit("|", 1)[-1] != self.nodes[1]:
            raise AssertionError(f"新しい選択へ追従していません: {names}")
        self._capture("02-single-selection.png")
        bd_channel_box.dispose()

    def _reopen_for_reload(self) -> None:
        """現在の選択でcallback基準値を記録し、reload対象を表示する。"""
        from bd_tools import bd_channel_box

        self.baseline_callbacks = self._callback_counts()
        self.window = bd_channel_box.show()

    def _reload(self) -> None:
        """表示中のWindowを含めてutilとtoolsをreloadする。"""
        import bd_tools

        bd_tools.reload_package(reload_util=True)
        self.steps.append("reload_util_and_tools")

    def _show_after_reload(self) -> None:
        """reloadで古いWindowとcallbackが消えたことを確認して再表示する。"""
        from bd_tools import bd_channel_box
        from bd_util.ui import qt

        if self.window is not None and qt.isValid(self.window):
            raise AssertionError("reload後に古いWindowが残っています")
        if self._callback_counts() != self.baseline_callbacks:
            raise AssertionError("reload後にnode callbackが残っています")
        self.window = bd_channel_box.show()
        self.steps.append("show_after_reload")

    def _capture_after_reload(self) -> None:
        """reload後の表示結果を保存し、負荷測定前に入力Windowを終了する。"""
        from bd_tools import bd_channel_box
        from bd_util.ui import FloatValueStepSpinBox

        if self._require_window().widget.wheel_editing_action.isChecked():
            raise AssertionError("reload後にホイール編集設定を復元できません")
        step = self._row("translate.translateX").editor
        if (
            not isinstance(step, FloatValueStepSpinBox)
            or step.singleStep() != _PERSISTED_STEP
        ):
            raise AssertionError("reload後に属性Stepを復元できません")
        self._capture("03-after-reload.png")
        bd_channel_box.dispose()

    def _benchmark(self) -> None:
        """10ノード・30追加属性で生成、一括入力、選択切替を計測する。"""
        from maya import cmds

        from bd_tools import bd_channel_box
        from bd_util.ui import FloatValueStepSpinBox

        cmds.file(new=True, force=True)
        self.nodes = []
        for node_index in range(10):
            node = cmds.createNode(
                "transform", name=f"bdChannelBoxBench{node_index}"
            )
            for attribute_index in range(30):
                cmds.addAttr(
                    node,
                    longName=f"field{attribute_index:02d}",
                    attributeType="double",
                    keyable=True,
                )
            self.nodes.append(node)
        cmds.select(self.nodes, replace=True)
        self._flush_gui()
        baseline_count = sum(self._callback_counts().values())

        # 起動時の行構築とQtへの表示更新を同じ測定区間へ含める
        started = time.perf_counter()
        self.window = bd_channel_box.show()
        self._flush_gui()
        self.measurements["create_window_ms"] = round(
            (time.perf_counter() - started) * 1000, 3
        )
        self.measurements["nodes"] = len(self.nodes)
        self.measurements["rows"] = len(self.window.widget.row_widgets)
        self.measurements["node_callbacks_added"] = (
            sum(self._callback_counts().values()) - baseline_count
        )
        row = self._row("field00")
        if not isinstance(row.editor, FloatValueStepSpinBox):
            raise AssertionError("負荷測定用float属性のViewがありません")
        started = time.perf_counter()
        row.editor.spin_box.setValue(0.5)
        self._flush_gui()
        self.measurements["edit_ten_targets_ms"] = round(
            (time.perf_counter() - started) * 1000, 3
        )
        self._assert_values("field00", (0.5,) * 10)

        # 行数の違いによる値同期の負荷を、warm-up後の中央値で比較する
        for selected in ("keyable", "all"):
            self.window.widget.controller.set_attribute_filter(selected)
            self._flush_gui()
            view = self._row("field00").editor
            if not isinstance(view, FloatValueStepSpinBox):
                raise AssertionError("負荷測定用float属性のViewがありません")
            samples: list[float] = []
            for index in range(11):
                started = time.perf_counter()
                view.spin_box.setValue(float(index + 1))
                self._flush_gui()
                elapsed = (time.perf_counter() - started) * 1000
                if index >= 2:
                    samples.append(elapsed)
            self.measurements[f"edit_{selected}_rows"] = len(
                self.window.widget.row_widgets
            )
            self.measurements[f"edit_{selected}_median_ms"] = round(
                statistics.median(samples), 3
            )
            self._assert_values("field00", (11.0,) * 10)
        self.window.widget.controller.set_attribute_filter("visible")
        self._flush_gui()

        # 全選択から1ノードへの切替と古い入力行の破棄を計測する
        started = time.perf_counter()
        cmds.select(self.nodes[-1], replace=True)
        self._flush_gui()
        self.measurements["selection_to_one_node_ms"] = round(
            (time.perf_counter() - started) * 1000, 3
        )
        if len(self.window.widget.controller.node_names) != 1:
            raise AssertionError("負荷測定時に選択追従が完了していません")
        self._benchmark_selection()
        self.steps.append("benchmark_10_nodes_30_attributes")

    def _benchmark_selection(self) -> None:
        """代表ノードを切り替え、行の破棄と描画まで含む中央値を記録する。"""
        from maya import cmds

        from bd_tools.bd_channel_box.controller import (
            ChannelAttributeFilter,
            ChannelBoxMode,
        )

        widget = self._require_window().widget
        cases: tuple[
            tuple[int, ChannelBoxMode, ChannelAttributeFilter], ...
        ] = (
            (1, "values", "visible"),
            (1, "values", "all"),
            (10, "values", "all"),
            (1, "states", "all"),
        )
        for count, mode, selected in cases:
            widget.controller.set_mode(mode)
            widget.controller.set_attribute_filter(selected)
            self._flush_gui()
            samples: list[float] = []
            for index in range(9):
                targets = (
                    self.nodes if index % 2 else list(reversed(self.nodes))
                )[:count]
                started = time.perf_counter()
                cmds.select(targets, replace=True)
                self._flush_gui()
                elapsed = (time.perf_counter() - started) * 1000
                if len(widget.controller.node_names) != count or (
                    widget.controller.node_names[0].rsplit("|", 1)[-1]
                    != targets[0]
                ):
                    raise AssertionError("計測中に選択追従が完了していません")
                if index >= 2:
                    samples.append(elapsed)
            key = f"selection_{mode}_{selected}_{count}_nodes"
            self.measurements[f"{key}_median_ms"] = round(
                statistics.median(samples), 3
            )
            self.measurements[f"{key}_rows"] = len(widget.row_widgets)
        self._assert_values("field00", (11.0,) * len(self.nodes))

    def _finish(self) -> None:
        """すべての操作結果を保存し、検証専用Mayaを終了する。"""
        from bd_tools import bd_channel_box

        bd_channel_box.dispose()
        self.steps.append("dispose")
        if os.environ.get(_PREPARE_RESTART_VARIABLE) == "1":
            self._prepare_restart()
        self._complete(True)

    def _prepare_restart(self) -> None:
        """独立profileへfloating配置を保存し、次のMaya起動の検証資料を残す。"""
        from maya import cmds
        from bd_tools import bd_channel_box

        self.window = bd_channel_box.show()
        cmds.workspaceControl(
            bd_channel_box.WORKSPACE_CONTROL_NAME,
            edit=True,
            floating=True,
            resizeWidth=420,
            resizeHeight=360,
        )
        self._flush_gui()
        host = self._require_window().window()
        geometry = host.geometry().getRect()
        cmds.workspaceLayoutManager(save=True)
        cmds.savePrefs(general=True, uiLayout=True)
        _write_json(
            self.output / "prepared-restart.json",
            {
                "maya_version": str(cmds.about(version=True)),
                "control_name": bd_channel_box.WORKSPACE_CONTROL_NAME,
                "geometry": geometry,
            },
        )
        self.steps.append("save_floating_workspace_for_restart")

    def _inspect_restart(self) -> None:
        """showを呼ぶ前に、Mayaの保存workspaceとuiScriptだけで復元したUIを確認する。"""
        from maya import cmds
        from bd_tools import bd_channel_box
        from bd_util.ui import qt

        self._inspect_clipboard_across_maya_processes()
        name = bd_channel_box.WORKSPACE_CONTROL_NAME
        if not cmds.workspaceControl(name, query=True, exists=True):
            raise AssertionError(
                "Maya再起動でworkspaceControlが復元されません"
            )
        windows = [
            widget
            for widget in qt.QApplication.allWidgets()
            if isinstance(widget, bd_channel_box.ChannelBoxWindow)
        ]
        if len(windows) != 1:
            raise AssertionError(
                f"復元されたbdChannelBoxの数が不正です: {len(windows)}"
            )
        self.window = windows[0]
        if not cmds.workspaceControl(name, query=True, floating=True):
            raise AssertionError("保存したfloating配置が復元されません")
        saved = json.loads(
            (self.output / "prepared-restart.json").read_text(encoding="utf-8")
        )
        geometry = self.window.window().geometry().getRect()
        if any(abs(a - b) > 40 for a, b in zip(geometry, saved["geometry"])):
            raise AssertionError(
                f"floatingの保存配置と復元結果が異なります: {saved['geometry']} -> {geometry}"
            )
        if bd_channel_box.show() is not self.window:
            raise AssertionError("再起動後のshowでWindowが重複しました")
        self.steps.append("maya_restart_restores_workspace_and_content")

    def _inspect_clipboard_across_maya_processes(self) -> None:
        """前のMayaがOSへ残した属性値を読取り、元のclipboardへ復元する。"""
        from bd_util.maya.ui import MayaScalarValueClipboard
        from bd_util.ui import qt

        saved_path = self.output / "clipboard-original.json"
        if not saved_path.is_file():
            raise AssertionError("再起動前のclipboard退避dataがありません")
        saved_items = json.loads(saved_path.read_text(encoding="utf-8"))
        clipboard = qt.QApplication.clipboard()
        restored = qt.QtCore.QMimeData()
        for item in saved_items:
            restored.setData(
                item["format"],
                qt.QByteArray(base64.b64decode(item["data"])),
            )
        try:
            transfer = MayaScalarValueClipboard().read()
            copied = {
                snapshot.path: snapshot.value
                for snapshot in transfer.nodes[0].values
            }
            expected = {"weight": 0.25, "enabled": False, "mode": 5}
            if any(
                copied.get(path) != value for path, value in expected.items()
            ):
                raise AssertionError(
                    f"別Maya processのclipboard値が不正です: {copied}"
                )
            if len(copied) <= len(expected):
                raise AssertionError(
                    "別Maya processで全対応属性を読取れていません"
                )
        finally:
            clipboard.setMimeData(restored)
            self._flush_gui()
        self.steps.append("clipboard_transfer_across_maya_processes")

    def _edit_after_restart(self) -> None:
        """復元したUIが新しい選択と一括入力へ追従することを確認する。"""
        from bd_util.ui import FloatValueStepSpinBox

        view = self._row("translate.translateX").editor
        if not isinstance(view, FloatValueStepSpinBox):
            raise AssertionError("復元したUIに入力Viewがありません")
        if view.singleStep() != _PERSISTED_STEP:
            raise AssertionError("Maya再起動後に属性Stepを復元できません")
        view.spin_box.setValue(0.5)
        self._assert_values("translateX", (0.5, 0.5))
        if (
            self._require_window()
            .widget.scroll_area.horizontalScrollBar()
            .maximum()
        ):
            raise AssertionError(
                "再起動後の標準属性の入力欄が横幅に収まりません"
            )
        self._capture("07-after-maya-restart.png")
        self.steps.append("edit_multiple_nodes_after_maya_restart")

    @staticmethod
    def _flush_gui() -> None:
        """予約された構成更新とQObject削除を進め、測定区間へ含める。"""
        from bd_util.ui import qt

        for _ in range(3):
            qt.QApplication.processEvents()
            qt.QApplication.sendPostedEvents(
                None, qt.QEvent.Type.DeferredDelete
            )

    def _require_window(self) -> ChannelBoxWindow:
        """生存している検証対象Windowを返す。"""
        from bd_util.ui import qt

        if self.window is None or not qt.isValid(self.window):
            raise AssertionError("bdChannelBoxのWindowがありません")
        return self.window

    def _row(self, attribute_name: str) -> AttributeRowWidget:
        """指定した属性pathに対応する表示中の入力行を返す。"""
        from bd_tools.bd_channel_box.widget import AttributeRowWidget

        window = self._require_window()
        for row in window.widget.row_widgets:
            if (
                isinstance(row, AttributeRowWidget)
                and row.row.attribute.path == attribute_name
            ):
                window.widget.scroll_area.ensureWidgetVisible(row)
                return row
        raise AssertionError(f"入力行が見つかりません: {attribute_name}")

    def _state_row(self, attribute_name: str) -> AttributeStateRowWidget:
        """指定した属性pathに対応する表示中の状態行を返す。"""
        from bd_tools.bd_channel_box.widget import AttributeStateRowWidget

        window = self._require_window()
        for row in window.widget.row_widgets:
            if (
                isinstance(row, AttributeStateRowWidget)
                and row.row.attribute.path == attribute_name
            ):
                window.widget.scroll_area.ensureWidgetVisible(row)
                return row
        self._capture("failure-state-row.png")
        raise AssertionError(
            f"状態行が見つかりません: {attribute_name}; "
            f"mode={window.widget.controller.mode}, "
            f"filter={window.widget.controller.attribute_filter}, "
            f"rows={len(window.widget.row_widgets)}, "
            f"error={window.widget.message_label.text()}"
        )

    def _row_layout(
        self, row: AttributeRowWidget | AttributeStateRowWidget
    ) -> tuple[int, int, int, int]:
        """同じ属性のWindow幅と名前・入力列の位置を取得する。"""
        from bd_util.ui import qt

        window = self._require_window()
        return (
            window.width(),
            row.name_label.width(),
            row.editor.mapTo(window.widget, qt.QPoint(0, 0)).x(),
            row.editor.width(),
        )

    def _assert_state_layout(self, row: AttributeStateRowWidget) -> None:
        """Window幅を維持し、200pxの操作欄へ全ボタンが収まることを確認する。"""
        actual = self._row_layout(row)
        expected = self._value_layout
        if expected is None or (actual[0], actual[3]) != (
            expected[0],
            200,
        ):
            raise AssertionError(
                f"Window幅または設定モードの200px幅が異なります: "
                f"{self._value_layout} -> {actual}"
            )
        if (
            self._require_window()
            .widget.scroll_area.horizontalScrollBar()
            .maximum()
        ):
            raise AssertionError("状態入力欄がWindow幅に収まりません")
        for button in (*row.display_buttons.values(), row.lock_check_box):
            if (
                button.width() < button.sizeHint().width()
                or button.x() + button.width() > row.editor.width()
            ):
                raise AssertionError("状態ボタンが200pxの操作欄に収まりません")

    def _attribute_states(
        self, name: str
    ) -> tuple[tuple[bool, bool, bool], ...]:
        """Mayaの実属性からkeyable・channelBox・lockを読み取る。"""
        from maya import cmds

        return tuple(
            (
                bool(cmds.getAttr(f"{node}.{name}", keyable=True)),
                bool(cmds.getAttr(f"{node}.{name}", channelBox=True)),
                bool(cmds.getAttr(f"{node}.{name}", lock=True)),
            )
            for node in self.nodes
        )

    def _select_radio_button(self, button: qt.QRadioButton) -> None:
        """ラジオボタンを実マウス入力で選択し、遅延同期まで処理する。"""
        from bd_util.ui import qt

        self._flush_gui()
        for event_type in (
            qt.QEvent.Type.MouseButtonPress,
            qt.QEvent.Type.MouseButtonRelease,
        ):
            self._mouse(button, event_type, button.rect().center())
        self._flush_gui()

    def _select_combo_item(self, combo: qt.QComboBox, index: int) -> None:
        """ComboBoxを開いて項目をマウスで選び、通常の選択通知を通す。"""
        from bd_util.ui import qt

        if not 0 <= index < combo.count():
            raise AssertionError(f"選択するComboBox項目がありません: {index}")
        combo.showPopup()
        self._flush_gui()
        view = combo.view()
        model_index = combo.model().index(index, 0)
        view.scrollTo(model_index)
        position = view.visualRect(model_index).center()
        for event_type in (
            qt.QEvent.Type.MouseButtonPress,
            qt.QEvent.Type.MouseButtonRelease,
        ):
            self._mouse(view.viewport(), event_type, position)
        self._flush_gui()

    def _assert_values(
        self, name: str, expected: tuple[float | bool, ...]
    ) -> None:
        """表示用情報を経由せずMayaから各対象の実値を取得して比較する。"""
        from maya import cmds

        values = tuple(cmds.getAttr(f"{node}.{name}") for node in self.nodes)
        if len(values) != len(expected) or any(
            abs(a - b) > 1e-8 for a, b in zip(values, expected)
        ):
            raise AssertionError(
                f"{name}: expected={expected}, actual={values}"
            )

    @staticmethod
    def _open_context_menu(widget: qt.QWidget) -> None:
        """属性名へ右クリック通知を送り、通常のイベント伝播でメニューを開く。"""
        from bd_util.ui import qt

        position = widget.rect().center()
        event = qt.QtGui.QContextMenuEvent(
            qt.QtGui.QContextMenuEvent.Reason.Mouse,
            position,
            widget.mapToGlobal(position),
        )
        qt.QApplication.sendEvent(widget, event)

    @staticmethod
    def _key(
        widget: qt.QWidget,
        key: int,
        *,
        text: str = "",
        modifiers: qt.Qt.KeyboardModifier | None = None,
    ) -> None:
        """Widgetへキーの押下と解放を送り、実際の入力処理を通す。"""
        from bd_util.ui import qt

        widget.setFocus()
        if modifiers is None:
            modifiers = qt.Qt.KeyboardModifier.NoModifier
        for event_type in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
            event = qt.QtGui.QKeyEvent(event_type, key, modifiers, text)
            qt.QApplication.sendEvent(widget, event)

    @staticmethod
    def _mouse(
        widget: qt.QWidget, event_type: qt.QEvent.Type, position: qt.QPoint
    ) -> None:
        """Widget内の位置へマウス操作を送り、連続編集の開始と終了を通す。"""
        from bd_util.ui import qt

        button = qt.Qt.MouseButton.LeftButton
        buttons = qt.Qt.MouseButton.LeftButton
        if event_type == qt.QEvent.Type.MouseMove:
            button = qt.Qt.MouseButton.NoButton
        elif event_type == qt.QEvent.Type.MouseButtonRelease:
            buttons = qt.Qt.MouseButton.NoButton
        event = qt.QtGui.QMouseEvent(
            event_type,
            qt.QPointF(position),
            qt.QPointF(widget.mapToGlobal(position)),
            button,
            buttons,
            qt.Qt.KeyboardModifier.NoModifier,
        )
        qt.QApplication.sendEvent(widget, event)

    @staticmethod
    def _wheel(widget: qt.QWidget) -> None:
        """Windowsの入力経路で、Qtの自動フォーカス処理を含めて検証する。"""
        import ctypes
        from ctypes import wintypes

        # sendEventではspontaneousにならず、WheelFocusの自動移動を再現しない
        window = widget.window()
        position = widget.mapTo(window, widget.rect().center())
        ratio = window.devicePixelRatioF()
        point = wintypes.POINT(
            round(position.x() * ratio), round(position.y() * ratio)
        )
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ClientToScreen.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.POINT),
        )
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.SendMessageW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.SendMessageW.restype = wintypes.LPARAM
        handle = int(window.winId())
        if not user32.ClientToScreen(handle, ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        coordinates = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
        user32.SendMessageW(handle, 0x020A, 120 << 16, coordinates)

    def _capture(self, filename: str) -> None:
        """現在のWindowをQtからPNGとして保存する。"""
        window = self._require_window()
        image_path = self.output / filename
        if not window.grab().save(str(image_path)):
            raise RuntimeError(f"Window画像を保存できません: {image_path}")
        self.screenshots.append(str(image_path))

    def _capture_maya(self, filename: str) -> None:
        """独立したMaya main windowを描画し、ドッキング位置の確認画像を保存する。"""
        from bd_util.maya.ui import get_main_window

        window = get_main_window()
        image_path = self.output / filename
        if window is None or not window.grab().save(str(image_path)):
            raise RuntimeError("Maya全体のドッキング画像を保存できません")
        self.screenshots.append(str(image_path))

    def _callback_counts(self) -> dict[str, int]:
        """検証nodeに登録されたMaya callbackの本数を返す。"""
        from maya.api import OpenMaya as om

        result: dict[str, int] = {}
        for name in self.nodes:
            selection = om.MSelectionList()
            selection.add(name)
            result[name] = len(
                om.MMessage.nodeCallbacks(selection.getDependNode(0))
            )
        return result

    def _complete(self, success: bool, error: str | None = None) -> None:
        """結果を確定し、この検証processだけを正常な経路で終了する。"""
        from maya import cmds, mel

        faulthandler.cancel_dump_traceback_later()
        self._trace_file.close()
        _write_json(
            self.output
            / (
                "result-restart.json"
                if self._phase == "restart"
                else "result.json"
            ),
            {
                "success": success,
                "maya_version": cmds.about(version=True),
                "process_id": os.getpid(),
                "steps": self.steps,
                "screenshots": self.screenshots,
                "measurements": self.measurements,
                "diagnostics": self.diagnostics,
                "error": error,
            },
        )
        # Python callbackを戻してから、Mayaのnative MEL idleで終了する
        exit_code = 0 if success else 1
        mel.eval(
            "evalDeferred -lowestPriority "
            f'"quit -force -exitCode {exit_code};";'
        )

    def _record_state(self, stage: str) -> None:
        """各段階のUndo状態を保存し、起動時処理の割込みを診断する。"""
        from maya import cmds
        from maya.api import OpenMaya as om

        self.diagnostics.append(
            {
                "stage": stage,
                "elapsed_seconds": round(
                    time.perf_counter() - self._started_at, 3
                ),
                "maya_state": int(om.MGlobal.mayaState()),
                "undo_enabled": bool(cmds.undoInfo(query=True, state=True)),
                "undo_queue_empty": bool(
                    cmds.undoInfo(query=True, undoQueueEmpty=True)
                ),
                "undo_name": cmds.undoInfo(query=True, undoName=True),
            }
        )


def _start_inside_maya() -> None:
    """起動処理完了後のMaya event loopでUI検証を始める。"""
    import __main__

    output = Path(os.environ[_OUTPUT_VARIABLE]).resolve()
    session = _MayaSmokeSession(output)
    # singleShotのbound method参照だけへ寿命を委ねず、専用processで保持する
    setattr(__main__, "_bd_tools_bd_channel_box_qa_session", session)
    session.defer_until_idle()


def _launch(
    maya_version: str,
    util_root: Path,
    timeout: int,
    *,
    prepare_restart: bool = False,
    restart_from: Path | None = None,
) -> int:
    """固有の設定と作業ディレクトリを使う検証Maya processを起動する。"""
    repository = Path(__file__).resolve().parents[1]
    executable = Path(
        f"C:/Program Files/Autodesk/Maya{maya_version}/bin/maya.exe"
    )
    if not executable.is_file():
        raise FileNotFoundError(executable)
    util_python = util_root / "bakedanuki" / "bakedanuki-util" / "python"
    if not (util_python / "bd_util" / "__init__.py").is_file():
        raise FileNotFoundError(util_python)

    # 既存Mayaの設定、起動script、作業sceneを参照しないprocess環境にする
    phase = "restart" if restart_from is not None else "initial"
    if restart_from is None:
        output = Path(
            tempfile.mkdtemp(prefix=f"bd-channel-box-maya{maya_version}-")
        )
        for name in ("prefs", "env", "project", "scripts"):
            (output / name).mkdir()
    else:
        output = restart_from.resolve()
        # 通常のMaya設定を再起動検証に流用せず、このrunnerの保存資料だけを許可する
        if not output.name.startswith(f"bd-channel-box-maya{maya_version}-"):
            raise ValueError(
                "このrunnerが作成した検証ディレクトリを指定してください"
            )
        prepared = json.loads(
            (output / "prepared-restart.json").read_text(encoding="utf-8")
        )
        if prepared["maya_version"] != maya_version:
            raise ValueError("再起動前後のMaya versionが異なります")
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    environment["MAYA_APP_DIR"] = str(output / "prefs")
    environment["MAYA_ENV_DIR"] = str(output / "env")
    environment["MAYA_PROJECT"] = str(output / "project")
    environment["MAYA_SCRIPT_PATH"] = str(output / "scripts")
    environment["MAYA_SKIP_USERSETUP_PY"] = "1"
    environment["MAYA_DISABLE_ADP"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment[_OUTPUT_VARIABLE] = str(output)
    environment[_PHASE_VARIABLE] = phase
    environment[_PREPARE_RESTART_VARIABLE] = "1" if prepare_restart else "0"
    environment["BAKEDANUKI_UTIL_ROOT"] = str(util_root)
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(repository / "bakedanuki" / "bakedanuki-tools" / "python"),
            str(util_python),
        )
    )
    environment["MAYA_MODULE_PATH"] = os.pathsep.join(
        (
            str(repository / "bakedanuki" / "modules"),
            str(util_root / "bakedanuki" / "modules"),
        )
    )

    # MELの引用規則に合わせた起動ファイルから同じPython runnerを呼び出す
    python_command = (
        "import runpy; runpy.run_path("
        + repr(Path(__file__).resolve().as_posix())
        + ", run_name='__maya_ui_smoke__')"
    )
    mel_command = python_command.replace("\\", "\\\\").replace('"', '\\"')
    startup_script = output / f"startup-{phase}.mel"
    startup_script.write_text(f'python("{mel_command}");\n', encoding="utf-8")
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    # Mayaの補助processにもrunnerの出力pipeを引き継がせない
    result_path = output / (
        "result-restart.json" if phase == "restart" else "result.json"
    )
    # 同じprofileの再検証で、前回の成功結果を今回の結果として扱わない
    result_path.unlink(missing_ok=True)
    with (output / f"process-{phase}.log").open("wb") as process_log:
        process = subprocess.Popen(
            [
                str(executable),
                "-noAutoloadPlugins",
                "-proj",
                str(output / "project"),
                "-log",
                str(output / f"maya-{phase}.log"),
                "-script",
                str(startup_script),
            ],
            cwd=str(output),
            env=environment,
            startupinfo=startup_info,
            stdin=subprocess.DEVNULL,
            stdout=process_log,
            stderr=subprocess.STDOUT,
        )
        print(
            json.dumps(
                {
                    "process_id": process.pid,
                    "output": str(output),
                    "phase": phase,
                }
            ),
            flush=True,
        )
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # 起動した専用processだけを停止し、検証資料は削除せず残す
            process.terminate()
            process.wait(timeout=30)
            if result_path.is_file():
                print(result_path.read_text(encoding="utf-8"), flush=True)
                raise RuntimeError(
                    "操作結果は保存済みですが、Maya本体の終了が"
                    f"時間内に完了しませんでした: {output}"
                ) from None
            raise RuntimeError(
                f"Maya UI検証が時間内に完了しませんでした: {output}"
            ) from None
    if not result_path.is_file():
        raise RuntimeError(f"Maya UI検証結果がありません: {output}")
    print(result_path.read_text(encoding="utf-8"), flush=True)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return 0 if result["success"] and exit_code == 0 else 1


def main() -> int:
    """Maya versionとutil配置を解釈して独立したUI検証を実行する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maya-version", choices=("2025", "2026", "2027"), default="2025"
    )
    parser.add_argument("--util-root", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    restart_group = parser.add_mutually_exclusive_group()
    restart_group.add_argument("--prepare-restart", action="store_true")
    restart_group.add_argument("--restart-from", type=Path)
    arguments = parser.parse_args()
    util_root = arguments.util_root or Path(
        os.environ.get(
            "BAKEDANUKI_UTIL_ROOT",
            str(Path(__file__).resolve().parents[2] / "bakedanuki-util"),
        )
    )
    return _launch(
        arguments.maya_version,
        util_root.resolve(),
        arguments.timeout,
        prepare_restart=arguments.prepare_restart,
        restart_from=arguments.restart_from,
    )


if __name__ == "__main__":
    raise SystemExit(main())
elif __name__ == "__maya_ui_smoke__":
    _start_inside_maya()
