# coding: utf-8
"""独立したMaya本体でChannel Editorの表示と終了を検証する。"""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import subprocess
import tempfile
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bd_tools.channel_editor.ui import ChannelEditorWindow
    from bd_tools.channel_editor.widget import AttributeRowWidget
    from bd_util.ui import qt

_OUTPUT_VARIABLE = "BAKEDANUKI_TOOLS_UI_QA_OUTPUT"
_PHASE_VARIABLE = "BAKEDANUKI_TOOLS_UI_QA_PHASE"
_PREPARE_RESTART_VARIABLE = "BAKEDANUKI_TOOLS_UI_QA_PREPARE_RESTART"
_STARTUP_IDLE_COMMAND = (
    "import __main__; "
    "__main__._bd_tools_channel_editor_qa_session.begin_when_idle()"
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
        self._trace_file = (output / f"python-stacks-{self._phase}.log").open(
            "w", encoding="utf-8"
        )
        faulthandler.dump_traceback_later(
            45, repeat=True, file=self._trace_file
        )
        self.window: ChannelEditorWindow | None = None
        self.nodes: list[str] = []
        self.baseline_callbacks: dict[str, int] = {}
        self.steps: list[str] = []
        self.screenshots: list[str] = []
        self.measurements: dict[str, float | int] = {}
        self.diagnostics: list[dict[str, object]] = []
        self._started_at = time.perf_counter()
        self._startup_idle_checks = 0
        self._stage_index = 0
        self._stages = (
            self._setup_scene,
            self._show,
            self._inspect,
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
            self._edit_float,
            self._undo_float,
            self._drag_float,
            self._undo_drag,
            self._align_bool,
            self._undo_alignment,
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
            node = cmds.createNode("transform", name=f"channelEditorQA{index}")
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
            self.nodes.append(node)
        cmds.select(self.nodes, replace=True)
        self.steps.append("create_isolated_scene")

    def _show(self) -> None:
        """Maya標準UIの選択処理が完了してから入力Windowを表示する。"""
        from bd_tools import channel_editor

        self.baseline_callbacks = self._callback_counts()
        self.window = channel_editor.show()
        self.steps.append("show_multiple_selection")

    def _inspect(self) -> None:
        """実Windowの描画と対応Viewの存在を確認して画像を保存する。"""
        from bd_util.ui import BoolComboBox, FloatSliderSpinBox

        window = self._require_window()
        if not window.isVisible():
            raise AssertionError("Channel Editorが表示されていません")
        if not window.findChildren(BoolComboBox):
            raise AssertionError("boolのComboBoxが見つかりません")
        if not window.findChildren(FloatSliderSpinBox):
            raise AssertionError("min/max属性のSlider Viewが見つかりません")
        self._capture("01-multiple-selection.png")
        self.steps.append("inspect_rendered_views")

    def _float_dock(self) -> None:
        """初回の右ドックを確認し、Maya標準のfloatingへ切り替える。"""
        from maya import cmds
        from bd_tools import channel_editor

        name = channel_editor.WORKSPACE_CONTROL_NAME
        if not cmds.workspaceControl(name, query=True, exists=True):
            raise AssertionError("workspaceControlが作成されていません")
        if cmds.workspaceControl(name, query=True, floating=True):
            raise AssertionError("初回表示がドッキングされていません")
        if channel_editor.show() is not self._require_window():
            raise AssertionError("showでWindowが重複生成されました")
        self._capture_maya("05-docked.png")
        cmds.workspaceControl(name, edit=True, floating=True)

    def _inspect_floating(self) -> None:
        """floating後も同じ入力と監視が生存し、内容を表示できることを確認する。"""
        from maya import cmds
        from bd_tools import channel_editor

        if not cmds.workspaceControl(
            channel_editor.WORKSPACE_CONTROL_NAME, query=True, floating=True
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
        from bd_tools import channel_editor

        cmds.workspaceControl(
            channel_editor.WORKSPACE_CONTROL_NAME,
            edit=True,
            dockToMainWindow=("right", True),
        )

    def _inspect_redocked(self) -> None:
        """再ドッキング後も同じWindowで入力を継続できることを確認する。"""
        from maya import cmds
        from bd_tools import channel_editor

        if cmds.workspaceControl(
            channel_editor.WORKSPACE_CONTROL_NAME, query=True, floating=True
        ):
            raise AssertionError("Mayaへ再ドッキングできません")
        if channel_editor.show() is not self._require_window():
            raise AssertionError("再ドッキングでWindowが重複しました")
        self.steps.append("redock_to_maya_tab")

    def _reset_dock_layout(self) -> None:
        """配置resetが旧入力を破棄し、新しい右ドックへ戻すことを確認する。"""
        from maya import cmds
        from bd_tools import channel_editor
        from bd_util.ui import qt

        old_window = self._require_window()
        old_controller = old_window.widget.controller
        self.window = channel_editor.reset_layout()
        self._flush_gui()
        if not old_controller.is_disposed or qt.isValid(old_window):
            raise AssertionError(
                "配置reset後に旧Windowまたは入力が残っています"
            )
        if cmds.workspaceControl(
            channel_editor.WORKSPACE_CONTROL_NAME, query=True, floating=True
        ):
            raise AssertionError("配置reset後に右ドックへ戻りません")
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
        """stepの実入力は正本を維持し、値欄の増減にだけ反映する。"""
        from maya import cmds

        from bd_util.ui import FloatValueStepSpinBox, qt

        view = self._row("translate.translateX").editor
        if not isinstance(view, FloatValueStepSpinBox):
            raise AssertionError("translateXに値とstepのViewがありません")
        cmds.flushUndo()
        self._key(view.step_spin_box, qt.Qt.Key.Key_Down)
        if view.singleStep() != 0.1:
            raise AssertionError("stepの桁変更が反映されません")
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
        """ComboBoxのキー操作で複数ノードを同じ値へ変更する。"""
        from maya import cmds

        from bd_util.ui import BoolComboBox, qt

        row = self._row("enabled")
        if (
            not isinstance(row.editor, BoolComboBox)
            or not row.row.binding.is_mixed
        ):
            raise AssertionError("bool行に初期値の混在が表示されていません")
        cmds.flushUndo()
        self._key(row.editor, qt.Qt.Key.Key_End)
        self._assert_values("enabled", (True, True))
        self.steps.append("combobox_key_edit_multiple_nodes")

    def _undo_bool(self) -> None:
        """boolの一括変更が1回のUndoで戻ることを確認する。"""
        from maya import cmds

        cmds.undo()
        self._assert_values("enabled", (False, True))
        self.steps.append("undo_bool_once")

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

    def _close(self) -> None:
        """Maya側のclose操作からworkspaceControlごと完全破棄する。"""
        from maya import cmds
        from bd_tools import channel_editor

        cmds.workspaceControl(
            channel_editor.WORKSPACE_CONTROL_NAME, edit=True, close=True
        )
        self.steps.append("close")

    def _reopen(self) -> None:
        """close後のcallback解放を確認し、新しいWindowを表示する。"""
        from bd_tools import channel_editor
        from bd_util.ui import qt

        if self.window is not None and qt.isValid(self.window):
            raise AssertionError("close後にWindowが破棄されていません")
        if self._callback_counts() != self.baseline_callbacks:
            raise AssertionError("close後にnode callbackが残っています")
        self.window = channel_editor.show()
        self.steps.append("reopen_without_callback_leak")

    def _change_selection(self) -> None:
        """異なる選択へ切り替えて追従処理を実行する。"""
        from maya import cmds

        cmds.select(self.nodes[1], replace=True)
        self.steps.append("change_selection")

    def _close_for_reload(self) -> None:
        """選択追従を確認し、標準Mayaだけのcallback基準値を取り直す。"""
        from bd_tools import channel_editor

        window = self._require_window()
        names = window.widget.controller.node_names
        if len(names) != 1 or names[0].rsplit("|", 1)[-1] != self.nodes[1]:
            raise AssertionError(f"新しい選択へ追従していません: {names}")
        self._capture("02-single-selection.png")
        channel_editor.dispose()

    def _reopen_for_reload(self) -> None:
        """現在の選択でcallback基準値を記録し、reload対象を表示する。"""
        from bd_tools import channel_editor

        self.baseline_callbacks = self._callback_counts()
        self.window = channel_editor.show()

    def _reload(self) -> None:
        """表示中のWindowを含めてutilとtoolsをreloadする。"""
        import bd_tools

        bd_tools.reload_package(reload_util=True)
        self.steps.append("reload_util_and_tools")

    def _show_after_reload(self) -> None:
        """reloadで古いWindowとcallbackが消えたことを確認して再表示する。"""
        from bd_tools import channel_editor
        from bd_util.ui import qt

        if self.window is not None and qt.isValid(self.window):
            raise AssertionError("reload後に古いWindowが残っています")
        if self._callback_counts() != self.baseline_callbacks:
            raise AssertionError("reload後にnode callbackが残っています")
        self.window = channel_editor.show()
        self.steps.append("show_after_reload")

    def _capture_after_reload(self) -> None:
        """reload後の表示結果を保存し、負荷測定前に入力Windowを終了する。"""
        from bd_tools import channel_editor

        self._capture("03-after-reload.png")
        channel_editor.dispose()

    def _benchmark(self) -> None:
        """10ノード・30追加属性で生成、一括入力、選択切替を1回ずつ計測する。"""
        from maya import cmds

        from bd_tools import channel_editor
        from bd_util.ui import FloatValueStepSpinBox

        cmds.file(new=True, force=True)
        self.nodes = []
        for node_index in range(10):
            node = cmds.createNode(
                "transform", name=f"channelEditorBench{node_index}"
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
        self.window = channel_editor.show()
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

        # 全選択から1ノードへの切替と古い入力行の破棄を計測する
        started = time.perf_counter()
        cmds.select(self.nodes[-1], replace=True)
        self._flush_gui()
        self.measurements["selection_to_one_node_ms"] = round(
            (time.perf_counter() - started) * 1000, 3
        )
        if len(self.window.widget.controller.node_names) != 1:
            raise AssertionError("負荷測定時に選択追従が完了していません")
        self.steps.append("benchmark_10_nodes_30_attributes")

    def _finish(self) -> None:
        """すべての操作結果を保存し、検証専用Mayaを終了する。"""
        from bd_tools import channel_editor

        channel_editor.dispose()
        self.steps.append("dispose")
        if os.environ.get(_PREPARE_RESTART_VARIABLE) == "1":
            self._prepare_restart()
        self._complete(True)

    def _prepare_restart(self) -> None:
        """独立profileへfloating配置を保存し、次のMaya起動の検証資料を残す。"""
        from maya import cmds
        from bd_tools import channel_editor

        self.window = channel_editor.show()
        cmds.workspaceControl(
            channel_editor.WORKSPACE_CONTROL_NAME,
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
                "control_name": channel_editor.WORKSPACE_CONTROL_NAME,
                "geometry": geometry,
            },
        )
        self.steps.append("save_floating_workspace_for_restart")

    def _inspect_restart(self) -> None:
        """showを呼ぶ前に、Mayaの保存workspaceとuiScriptだけで復元したUIを確認する。"""
        from maya import cmds
        from bd_tools import channel_editor
        from bd_util.ui import qt

        name = channel_editor.WORKSPACE_CONTROL_NAME
        if not cmds.workspaceControl(name, query=True, exists=True):
            raise AssertionError(
                "Maya再起動でworkspaceControlが復元されません"
            )
        windows = [
            widget
            for widget in qt.QApplication.allWidgets()
            if isinstance(widget, channel_editor.ChannelEditorWindow)
        ]
        if len(windows) != 1:
            raise AssertionError(
                f"復元されたChannel Editorの数が不正です: {len(windows)}"
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
        if channel_editor.show() is not self.window:
            raise AssertionError("再起動後のshowでWindowが重複しました")
        self.steps.append("maya_restart_restores_workspace_and_content")

    def _edit_after_restart(self) -> None:
        """復元したUIが新しい選択と一括入力へ追従することを確認する。"""
        from bd_util.ui import FloatValueStepSpinBox

        view = self._row("translate.translateX").editor
        if not isinstance(view, FloatValueStepSpinBox):
            raise AssertionError("復元したUIに入力Viewがありません")
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

    def _require_window(self) -> ChannelEditorWindow:
        """生存している検証対象Windowを返す。"""
        from bd_util.ui import qt

        if self.window is None or not qt.isValid(self.window):
            raise AssertionError("Channel EditorのWindowがありません")
        return self.window

    def _row(self, attribute_name: str) -> AttributeRowWidget:
        """指定した属性pathに対応する表示中の入力行を返す。"""
        window = self._require_window()
        for row in window.widget.row_widgets:
            if row.row.attribute.path == attribute_name:
                window.widget.scroll_area.ensureWidgetVisible(row)
                return row
        raise AssertionError(f"入力行が見つかりません: {attribute_name}")

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
    setattr(__main__, "_bd_tools_channel_editor_qa_session", session)
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
            tempfile.mkdtemp(prefix=f"bd-channel-editor-maya{maya_version}-")
        )
        for name in ("prefs", "env", "project", "scripts"):
            (output / name).mkdir()
    else:
        output = restart_from.resolve()
        # 通常のMaya設定を再起動検証に流用せず、このrunnerの保存資料だけを許可する
        if not output.name.startswith(
            f"bd-channel-editor-maya{maya_version}-"
        ):
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
