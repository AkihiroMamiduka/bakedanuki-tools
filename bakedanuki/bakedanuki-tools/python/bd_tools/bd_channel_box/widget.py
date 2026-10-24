# coding: utf-8
"""bdChannelBoxの値入力と表示・ロック設定画面。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Literal, Protocol, TypeAlias, cast

from maya import cmds

from bd_util import Nodes
from bd_util.maya.ui import (
    ChannelDisplayState,
    MayaBoolPlugsBinding,
    MayaEnumPlugsBinding,
    MayaEditSession,
    MayaFloatPlugsBinding,
    MayaIntPlugsBinding,
    MayaNodeNameBinding,
    MayaPlugInputState,
    MayaStringPlugsBinding,
    get_channel_box_precision,
)
from bd_util.ui import (
    BoolCheckBox,
    CheckBoxSweep,
    DialogAnchorTracker,
    EnumComboBox,
    FloatStepProfile,
    FloatStepSetting,
    FloatSliderSpinBox,
    FloatStepMode,
    FloatUnitKind,
    FloatValueStepSpinBox,
    IntSpinBox,
    IntStepProfile,
    IntStepSetting,
    IntValueStepSpinBox,
    IntSliderSpinBox,
    RadioButtonSweep,
    StringLineEdit,
    qt,
)

from .controller import (
    ChannelAttributeFilter,
    ChannelBoxController,
    ChannelRow,
    ChannelStateRow,
    ROTATION_ATTRIBUTE_PATHS,
    RoundTransformKind,
    RotationDestination,
)
from .custom_filter_registry import CustomFilterRegistry
from .custom_filter_manager import CustomFilterManagerDialog
from .custom_filter_dialogs import create_registered_filter
from .custom_filter_setup import CustomFilterSetupPanel
from .custom_filters import CustomFilterSelection
from .filter_preferences import ValueFilterPreferences
from .table import ChannelTableView, TableRow

__all__ = [
    "AttributeRowMenu",
    "AttributeRowWidget",
    "AttributeStateRowWidget",
    "CustomFilterManagerDialog",
    "ChannelBoxWidget",
]

# 小数点を含む20文字程度の値を、上下ボタンと併せて表示する
_VALUE_FIELD_WIDTH = 156
_AUXILIARY_FIELD_WIDTH = 60
_FIELD_SPACING = 6
_NAME_EDITOR_SPACING = 0
_EDITOR_WIDTH = _VALUE_FIELD_WIDTH + _FIELD_SPACING + _AUXILIARY_FIELD_WIDTH
_NAME_FIELD_PREFERRED_WIDTH = 92
_NAME_FIELD_RIGHT_MARGIN = 4
_INPUT_STATE_WIDTH = 6
_INPUT_STATE_VERTICAL_INSET = 1
_NAME_CONFLICT_MESSAGE = (
    "ノード名が外部で変更されました。"
    "Enterで入力名を適用するか、Escapeで取り消してください。"
)
_NAME_IDLE_STYLE = (
    "background-color: palette(window); "
    "color: palette(window-text); "
    "border: none; "
    "padding-left: 3px; padding-right: 3px;"
)
_IndicatorState = MayaPlugInputState | Literal["locked"]
_INPUT_STATE_COLORS: dict[_IndicatorState, str] = {
    "nonkeyable": "#949494",
    "keyed": "#CD2729",
    "animated": "#DD727A",
    "key_altered": "#FDCBC4",
    "driven_key": "#5099DA",
    "expression": "#CBA5F1",
    "animation_layer": "#4DB6AC",
    "animation_clip": "#FFCC80",
    "muted": "#BFA182",
    "pair_blend": "#ACF1AC",
    "constraint": "#A3CBF0",
    "connected": "#F1F1A5",
    "locked": "#5C6874",
}
_INPUT_STATE_LABELS: dict[MayaPlugInputState, str] = {
    "unconnected": "入力接続なし",
    "nonkeyable": "入力接続なし・キー設定不可",
    "keyed": "現在時刻にキーあり",
    "animated": "アニメーションあり・現在時刻にキーなし",
    "key_altered": "キーの評価値と現在値が異なります",
    "driven_key": "Driven Keyの入力接続あり",
    "expression": "Expressionの入力接続あり",
    "animation_layer": "Animation Layerの入力接続あり",
    "animation_clip": "Animation Clipの入力接続あり",
    "muted": "入力接続がミュートされています",
    "pair_blend": "pairBlendの入力接続あり",
    "constraint": "constraintの入力接続あり",
    "connected": "その他の入力接続あり",
}
_PASTE_FILTER_OPTIONS: tuple[tuple[ChannelAttributeFilter, str, str], ...] = (
    ("all", "全て", "コピーした全項目を"),
    (
        "visible",
        "Keyable + ChannelBox",
        "基準ノードでkeyableまたはchannelboxのコピー項目を",
    ),
    ("keyable", "Keyable", "基準ノードでkeyableのコピー項目を"),
    (
        "channel_box",
        "ChannelBox",
        "基準ノードで非keyableかつchannelboxのコピー項目を",
    ),
    (
        "hidden",
        "Hide",
        "基準ノードでkeyableでもchannelboxでもないコピー項目を",
    ),
)
_RoundScope: TypeAlias = ChannelAttributeFilter | Literal["selected"]
_ROUND_DIGIT_EXAMPLE = "123456789012345"
_XYZ_ROUND_GROUPS: tuple[RoundTransformKind, ...] = (
    "translate",
    "rotate",
    "rotateAxis",
    "jointOrient",
)
_XYZ_ROUND_ATTRIBUTE_KINDS: dict[str, RoundTransformKind] = {
    f"{group}.{group}{axis}": group
    for group in _XYZ_ROUND_GROUPS
    for axis in "XYZ"
}
_JointChildCompensationAttr: TypeAlias = Literal["rotate", "jointOrient"]
_DISPLAY_OPTIONS: tuple[tuple[ChannelDisplayState, str, str], ...] = (
    ("keyable", "key", "Keyable: キー設定可能"),
    ("channel_box", "ch", "ChannelBox: キー設定不可・Channel Boxに表示"),
    ("hidden", "hide", "Hide: キー設定不可・Channel Boxから非表示"),
)
_SearchVisibility = Literal["never", "all_only", "always"]
_SEARCH_VISIBILITY_OPTIONS: tuple[tuple[_SearchVisibility, str, str], ...] = (
    ("never", "非表示", "検索欄を表示しません。"),
    (
        "all_only",
        "「全て」の場合のみ表示",
        "Attribute Filterが「全て」の場合だけ検索欄を表示します。",
    ),
    ("always", "常に表示", "全てのAttribute Filterで検索欄を表示します。"),
)
_ATTRIBUTE_FILTER_OPTIONS: tuple[tuple[str, ChannelAttributeFilter], ...] = (
    ("全て", "all"),
    ("keyable + channelbox", "visible"),
    ("keyable", "keyable"),
    ("channelbox", "channel_box"),
    ("hide", "hidden"),
)


def _require_integer_step(value: int | float) -> int:
    """混在行の境界だけで整数相当のfloatを検証し、正の整数へ変換する。"""
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("整数属性のStepには1以上の32-bit整数が必要です")
        value = int(value)
    return IntStepSetting("step", value).single_step


class _MenuActions(Protocol):
    """Qt同梱stubの版差を、使用するQActionの追加操作だけで閉じる。"""

    def addAction(self, action: qt.QAction, /) -> None:
        """作成済みのQActionをメニューへ追加する。"""
        ...


def _create_animation_layer_menu(
    parent: qt.QMenu, operation: Literal["add", "remove"]
) -> tuple[qt.QMenu, qt.QAction, qt.QAction]:
    """選択レイヤへの属性追加・除去メニューを両表示モードへ共通に作る。"""
    adding = operation == "add"
    title = (
        "アニメーションレイヤ：追加"
        if adding
        else "アニメーションレイヤ：除去"
    )
    menu = qt.QMenu(title, parent)
    menu.setToolTipsVisible(True)
    selected = qt.QAction("選択属性", menu)
    selected.setObjectName(f"animation_layer_{operation}_selected")
    selected.setToolTip(
        "選択属性を選択中のアニメーションレイヤへ追加"
        if adding
        else "選択属性を選択中のレイヤから除去（そのレイヤ上のキーも削除）"
    )
    all_keyable = qt.QAction("全 Keyable", menu)
    all_keyable.setObjectName(f"animation_layer_{operation}_all_keyable")
    all_keyable.setToolTip(
        "各選択ノードの全Keyable属性を選択中のレイヤへ追加"
        if adding
        else "各選択ノードの全Keyable属性を選択中のレイヤから除去"
        "（そのレイヤ上のキーも削除）"
    )
    actions = cast(_MenuActions, menu)
    actions.addAction(selected)
    actions.addAction(all_keyable)
    return menu, selected, all_keyable


def _use_row_context_menu(editor: qt.QWidget) -> None:
    """入力部品の右クリックを属性行へ渡し、値編集は維持する。"""
    find_children = cast(
        Callable[[type[qt.QWidget]], list[qt.QWidget]],
        getattr(editor, "findChildren"),
    )
    for widget in (editor, *find_children(qt.QWidget)):
        if not widget.isWindow():
            widget.setContextMenuPolicy(qt.Qt.ContextMenuPolicy.NoContextMenu)


class _AttributeNameLabel(qt.QLabel):
    """設定モードの長い属性名でも入力列を押し広げない名前欄。"""

    def __init__(self, text: str, parent: qt.QWidget) -> None:
        """右端に選択色が見える余白を持つ名前欄を作成する。"""
        super().__init__(text, parent)
        self.setContentsMargins(0, 0, _NAME_FIELD_RIGHT_MARGIN, 0)

    def sizeHint(self) -> qt.QSize:
        """属性名の文字数に依存しない推奨幅を返す。"""
        return qt.QSize(
            _NAME_FIELD_PREFERRED_WIDTH, super().sizeHint().height()
        )

    def minimumSizeHint(self) -> qt.QSize:
        """狭いドックでは名前欄を縮めて入力欄を維持する。"""
        return qt.QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, arg__1: qt.QtGui.QPaintEvent) -> None:
        """完全な名前を保持し、表示領域へ収まる文字列だけを描画する。"""
        del arg__1
        painter = qt.QPainter(self)
        painter.setPen(self.palette().color(qt.QPalette.ColorRole.WindowText))
        contents = self.contentsRect()
        painter.drawText(
            contents,
            self.alignment(),
            self.fontMetrics().elidedText(
                self.text(),
                qt.Qt.TextElideMode.ElideRight,
                contents.width(),
            ),
        )
        painter.end()


class _InputStateIndicator(qt.QWidget):
    """属性名と値欄の間に接続種類とロックを示す細い帯。"""

    def __init__(self, parent: qt.QWidget) -> None:
        """入力部品や選択paletteに依存しない描画領域を作る。"""
        super().__init__(parent)
        self._state: _IndicatorState = "unconnected"
        self.setFixedWidth(_INPUT_STATE_WIDTH)
        self.setSizePolicy(
            qt.QSizePolicy.Policy.Fixed, qt.QSizePolicy.Policy.Expanding
        )

    @property
    def input_state(self) -> _IndicatorState:
        """最後に描画した接続・ロックの表示状態を返す。"""
        return self._state

    def set_input_state(self, state: _IndicatorState) -> None:
        """表示状態が変わった場合だけ帯を再描画する。"""
        if state == self._state:
            return
        self._state = state
        self.update()

    def paintEvent(self, event: qt.QtGui.QPaintEvent) -> None:
        """通常背景を塗り、状態色だけを上下1px内側に描く。"""
        del event
        painter = qt.QPainter(self)
        painter.fillRect(
            self.rect(), self.palette().color(qt.QPalette.ColorRole.Window)
        )
        if self._state != "unconnected":
            painter.fillRect(
                self.rect().adjusted(
                    0,
                    _INPUT_STATE_VERTICAL_INSET,
                    0,
                    -_INPUT_STATE_VERTICAL_INSET,
                ),
                qt.QColor(_INPUT_STATE_COLORS[self._state]),
            )
        painter.end()


class _LockCheckBox(qt.QCheckBox):
    """基準のlockを二状態で表示し、明示入力で反対の状態を要求する。"""

    def nextCheckState(self) -> None:
        """基準がロック中なら解除、それ以外ならロックへ進む。"""
        self.setCheckState(
            qt.Qt.CheckState.Unchecked
            if self.checkState() == qt.Qt.CheckState.Checked
            else qt.Qt.CheckState.Checked
        )


class AttributeRowMenu(qt.QMenu):
    """初回の右クリックで生成する、値編集行の操作メニュー。"""

    def __init__(
        self, widget: AttributeRowWidget, align_callback: Callable[[], None]
    ) -> None:
        """属性の型に応じた項目を、従来の順序で作成する。"""
        super().__init__(widget)
        row = widget.row
        self.align_menu = qt.QMenu("表示ノードの値に揃える", self)
        self.align_action = qt.QAction("選択属性", self)
        self.align_action.setObjectName("align_selected")
        self.align_action.setToolTip(
            "選択した各属性を表示ノードの同じ属性の値へ揃える"
        )
        self.align_action.triggered.connect(align_callback)
        align_actions = cast(_MenuActions, self.align_menu)
        align_actions.addAction(self.align_action)
        self.align_filtered_actions: dict[
            ChannelAttributeFilter, qt.QAction
        ] = {}
        for display_filter, label, _description in _PASTE_FILTER_OPTIONS:
            action = qt.QAction(label, self)
            action.setObjectName(f"align_{display_filter}")
            action.setToolTip(
                f"表示ノードの{label}に該当する各属性値へ、"
                "他の選択ノードの同じ属性を揃える"
            )
            self.align_filtered_actions[display_filter] = action
            align_actions.addAction(action)
        self.keyframe_menu = qt.QMenu("キーフレーム", self)
        self.set_key_all_keyable_action = qt.QAction("全 Keyable", self)
        self.set_key_all_keyable_action.setObjectName("set_key_all_keyable")
        self.set_key_all_keyable_action.setToolTip(
            "選択ノード自身の全Keyable属性に現在時刻のキーを設定"
        )
        self.set_key_selected_action = qt.QAction("選択属性", self)
        self.set_key_selected_action.setObjectName("set_key_selected")
        self.set_key_selected_action.setToolTip(
            "選択した属性に現在時刻のキーを設定"
        )
        keyframe_actions = cast(_MenuActions, self.keyframe_menu)
        keyframe_actions.addAction(self.set_key_selected_action)
        keyframe_actions.addAction(self.set_key_all_keyable_action)
        self.breakdown_menu = qt.QMenu("ブレイクダウンフレーム", self)
        self.set_breakdown_all_keyable_action = qt.QAction("全 Keyable", self)
        self.set_breakdown_all_keyable_action.setObjectName(
            "set_breakdown_all_keyable"
        )
        self.set_breakdown_all_keyable_action.setToolTip(
            "選択ノード自身の全Keyable属性に現在時刻のブレイクダウンを設定"
        )
        self.set_breakdown_selected_action = qt.QAction("選択属性", self)
        self.set_breakdown_selected_action.setObjectName(
            "set_breakdown_selected"
        )
        self.set_breakdown_selected_action.setToolTip(
            "選択した属性に現在時刻のブレイクダウンを設定"
        )
        breakdown_actions = cast(_MenuActions, self.breakdown_menu)
        breakdown_actions.addAction(self.set_breakdown_selected_action)
        breakdown_actions.addAction(self.set_breakdown_all_keyable_action)
        self.mute_menu = qt.QMenu("ミュート", self)
        self.mute_selected_action = qt.QAction("選択属性", self)
        self.mute_selected_action.setObjectName("mute_selected")
        self.mute_selected_action.setToolTip(
            "選択属性の入力接続をミュート（Hide属性も対象）"
        )
        self.mute_all_animation_action = qt.QAction(
            "全アニメーション属性", self
        )
        self.mute_all_animation_action.setObjectName("mute_all_animation")
        self.mute_all_animation_action.setToolTip(
            "各選択ノードのKeyable／ChannelBox表示属性の入力接続をミュート"
            "（画面の検索・表示条件に依存しません）"
        )
        mute_actions = cast(_MenuActions, self.mute_menu)
        mute_actions.addAction(self.mute_selected_action)
        mute_actions.addAction(self.mute_all_animation_action)
        self.unmute_menu = qt.QMenu("ミュート解除", self)
        self.unmute_selected_action = qt.QAction("選択属性", self)
        self.unmute_selected_action.setObjectName("unmute_selected")
        self.unmute_selected_action.setToolTip(
            "選択属性のミュートを解除（Hide属性も対象）"
        )
        self.unmute_all_animation_action = qt.QAction(
            "全アニメーション属性", self
        )
        self.unmute_all_animation_action.setObjectName("unmute_all_animation")
        self.unmute_all_animation_action.setToolTip(
            "各選択ノードのKeyable／ChannelBox表示属性のミュートを解除"
            "（画面の検索・表示条件に依存しません）"
        )
        unmute_actions = cast(_MenuActions, self.unmute_menu)
        unmute_actions.addAction(self.unmute_selected_action)
        unmute_actions.addAction(self.unmute_all_animation_action)
        self.animation_copy_menu = qt.QMenu(
            "アニメーションカーブ：コピー", self
        )
        self.animation_copy_selected_action = qt.QAction("選択属性", self)
        self.animation_copy_selected_action.setObjectName(
            "animation_copy_selected"
        )
        self.animation_copy_selected_action.setToolTip(
            "選択属性の全時間のカーブをMayaのキー用clipboardへコピー"
        )
        self.animation_copy_all_action = qt.QAction(
            "全アニメーション属性", self
        )
        self.animation_copy_all_action.setObjectName("animation_copy_all")
        self.animation_copy_all_action.setToolTip(
            "各選択ノードのKeyable／ChannelBox表示属性のカーブをコピー"
        )
        animation_copy_actions = cast(_MenuActions, self.animation_copy_menu)
        animation_copy_actions.addAction(self.animation_copy_selected_action)
        animation_copy_actions.addAction(self.animation_copy_all_action)
        self.animation_paste_menu = qt.QMenu(
            "アニメーションカーブ：ペースト", self
        )
        self.animation_paste_same_action = qt.QAction(
            "コピー元と同じ属性", self
        )
        self.animation_paste_same_action.setObjectName("animation_paste_same")
        self.animation_paste_same_action.setToolTip(
            "コピー元と同じ正式属性pathへ現在時刻からカーブを挿入"
        )
        self.animation_paste_selected_action = qt.QAction("選択属性", self)
        self.animation_paste_selected_action.setObjectName(
            "animation_paste_selected"
        )
        self.animation_paste_selected_action.setToolTip(
            "一曲線は型を問わず選択属性へ、複数曲線は同じ正式pathへ挿入"
        )
        animation_paste_actions = cast(_MenuActions, self.animation_paste_menu)
        animation_paste_actions.addAction(self.animation_paste_selected_action)
        animation_paste_actions.addAction(self.animation_paste_same_action)
        self.animation_cut_menu = qt.QMenu(
            "アニメーションカーブ：カット", self
        )
        self.animation_cut_selected_action = qt.QAction("選択属性", self)
        self.animation_cut_selected_action.setObjectName(
            "animation_cut_selected"
        )
        self.animation_cut_selected_action.setToolTip(
            "選択属性の全時間のカーブをコピーして削除（Hide属性も対象）"
        )
        self.animation_cut_all_action = qt.QAction(
            "全アニメーション属性", self
        )
        self.animation_cut_all_action.setObjectName("animation_cut_all")
        self.animation_cut_all_action.setToolTip(
            "各選択ノードのKeyable／ChannelBox表示属性のカーブをカット"
        )
        animation_cut_actions = cast(_MenuActions, self.animation_cut_menu)
        animation_cut_actions.addAction(self.animation_cut_selected_action)
        animation_cut_actions.addAction(self.animation_cut_all_action)
        self.animation_delete_menu = qt.QMenu(
            "アニメーションカーブ：削除", self
        )
        self.animation_delete_selected_action = qt.QAction("選択属性", self)
        self.animation_delete_selected_action.setObjectName(
            "animation_delete_selected"
        )
        self.animation_delete_selected_action.setToolTip(
            "選択属性の全時間のキーを削除（Hide属性も対象）"
        )
        self.animation_delete_all_action = qt.QAction(
            "全アニメーション属性", self
        )
        self.animation_delete_all_action.setObjectName("animation_delete_all")
        self.animation_delete_all_action.setToolTip(
            "各選択ノードのKeyable／ChannelBox表示属性の全時間のキーを削除"
        )
        animation_delete_actions = cast(
            _MenuActions, self.animation_delete_menu
        )
        animation_delete_actions.addAction(
            self.animation_delete_selected_action
        )
        animation_delete_actions.addAction(self.animation_delete_all_action)
        (
            self.animation_layer_add_menu,
            self.animation_layer_add_selected_action,
            self.animation_layer_add_all_keyable_action,
        ) = _create_animation_layer_menu(self, "add")
        (
            self.animation_layer_remove_menu,
            self.animation_layer_remove_selected_action,
            self.animation_layer_remove_all_keyable_action,
        ) = _create_animation_layer_menu(self, "remove")
        self.copy_menu = qt.QMenu("コピー", self)
        self.copy_all_values_action = qt.QAction("全属性", self)
        self.copy_all_values_action.setObjectName("copy_all_values")
        self.copy_all_values_action.setToolTip(
            "基準ノードの対応する全属性値をOSクリップボードへコピー"
        )
        self.copy_selected_values_action = qt.QAction("選択属性", self)
        self.copy_selected_values_action.setObjectName("copy_selected_values")
        self.copy_selected_values_action.setToolTip(
            "基準ノードで選択中の属性値をOSクリップボードへコピー"
        )
        copy_actions = cast(_MenuActions, self.copy_menu)
        copy_actions.addAction(self.copy_selected_values_action)
        copy_actions.addAction(self.copy_all_values_action)
        self.paste_menu = qt.QMenu("ペースト", self)
        self.paste_copied_values_actions: dict[
            ChannelAttributeFilter, qt.QAction
        ] = {}
        for display_filter, label, description in _PASTE_FILTER_OPTIONS:
            action = qt.QAction(f"コピー元と同じ属性：{label}", self)
            action.setObjectName(
                "paste_copied_values"
                if display_filter == "all"
                else f"paste_copied_values_{display_filter}"
            )
            action.setToolTip(
                f"{description}選択ノードの同じ正式pathへ貼り付け"
            )
            self.paste_copied_values_actions[display_filter] = action
        self.paste_copied_values_action = self.paste_copied_values_actions[
            "all"
        ]
        self.paste_selected_values_action = qt.QAction("選択属性", self)
        self.paste_selected_values_action.setObjectName(
            "paste_values_to_selected"
        )
        self.paste_selected_values_action.setToolTip(
            "コピーした値を選択属性へ貼り付け"
        )
        paste_actions = cast(_MenuActions, self.paste_menu)
        paste_actions.addAction(self.paste_selected_values_action)
        for action in self.paste_copied_values_actions.values():
            paste_actions.addAction(action)
        self.round_menu: qt.QMenu | None = None
        self.round_scope_menus: dict[_RoundScope, qt.QMenu] = {}
        self.round_menu_decimals: int | None = None
        if isinstance(row.binding, MayaFloatPlugsBinding):
            self.round_menu = qt.QMenu("小数点の四捨五入", self)
            for scope, label in (
                ("selected", "選択属性"),
                *((key, title) for key, title, _ in _PASTE_FILTER_OPTIONS),
            ):
                submenu = qt.QMenu(label, self.round_menu)
                self.round_scope_menus[cast(_RoundScope, scope)] = submenu
                self.round_menu.addMenu(submenu)
        self.xyz_round_kind: RoundTransformKind | None = (
            _XYZ_ROUND_ATTRIBUTE_KINDS.get(row.attribute.path)
            if isinstance(row.binding, MayaFloatPlugsBinding)
            else None
        )
        self.xyz_round_menus: dict[bool, qt.QMenu] = {}
        self.xyz_round_leaf_menus: dict[
            tuple[bool, _JointChildCompensationAttr], qt.QMenu
        ] = {}
        self.xyz_round_menu_decimals: int | None = None
        if self.xyz_round_kind == "translate":
            menu = qt.QMenu(
                "translateXYZ 小数点の四捨五入（子の座標を保持）",
                self,
            )
            self.xyz_round_menus[False] = menu
            self.xyz_round_leaf_menus[(False, "rotate")] = menu
        elif self.xyz_round_kind is not None:
            for preserve_translation, label in (
                (False, "子の姿勢を保持"),
                (True, "子の座標/姿勢を保持"),
            ):
                menu = qt.QMenu(
                    f"{self.xyz_round_kind}XYZ 小数点の四捨五入（{label}）",
                    self,
                )
                self.xyz_round_menus[preserve_translation] = menu
                for child_attr in ("rotate", "jointOrient"):
                    child_menu = qt.QMenu(
                        f"子 joint は、{child_attr} で調整", menu
                    )
                    self.xyz_round_leaf_menus[
                        (preserve_translation, child_attr)
                    ] = child_menu
                    menu.addMenu(child_menu)
        self.rotation_set_target: RotationDestination | None = (
            cast(RotationDestination, row.attribute.path.split(".", 1)[0])
            if row.attribute.path in ROTATION_ATTRIBUTE_PATHS
            else None
        )
        self.child_set_action: qt.QAction | None = None
        if self.xyz_round_kind is not None:
            self.child_set_action = qt.QAction(
                (
                    "移動をセット（子を維持）"
                    if self.xyz_round_kind == "translate"
                    else "回転をセット（子を維持）"
                ),
                self,
            )
            self.child_set_action.setObjectName(
                "set_transform_compensate_children"
            )
            self.child_set_action.setToolTip(
                "基準ノードのみのXYZを設定し、直接の子の維持範囲を指定"
            )
        self.rotation_set_action: qt.QAction | None = None
        if self.rotation_set_target is not None:
            self.rotation_set_action = qt.QAction(
                "回転をセット（姿勢を維持）", self
            )
            self.rotation_set_action.setObjectName(
                "set_rotation_preserving_pose"
            )
            self.rotation_set_action.setToolTip(
                "設定先と補償先を選び、基準ノードのみの姿勢を保ってXYZを設定"
            )
        self.rotation_menu: qt.QMenu | None = None
        self.rotation_actions: dict[RotationDestination, qt.QAction] = {}
        if row.attribute.path in ROTATION_ATTRIBUTE_PATHS:
            self.rotation_menu = qt.QMenu("回転を集約", self)
            for destination in ("rotate", "rotateAxis", "jointOrient"):
                action = qt.QAction(
                    f"{destination} に集約", self.rotation_menu
                )
                action.setObjectName(f"consolidate_rotation_{destination}")
                action.setToolTip(
                    "選択中の各ノードの現在回転を"
                    f"{destination}へ集約し、ほかの回転属性をゼロにする"
                )
                self.rotation_actions[destination] = action
                cast(_MenuActions, self.rotation_menu).addAction(action)
        self.freeze_menu = qt.QMenu("フリーズ", self)
        self.freeze_translate_action = qt.QAction("移動", self)
        self.freeze_translate_action.setObjectName("freeze_translate")
        self.freeze_rotate_action = qt.QAction("回転", self)
        self.freeze_rotate_action.setObjectName("freeze_rotate")
        self.freeze_scale_action = qt.QAction("スケール", self)
        self.freeze_scale_action.setObjectName("freeze_scale")
        self.freeze_all_action = qt.QAction("全て", self)
        self.freeze_all_action.setObjectName("freeze_all")
        freeze_actions = cast(_MenuActions, self.freeze_menu)
        for action in (
            self.freeze_translate_action,
            self.freeze_rotate_action,
            self.freeze_scale_action,
            self.freeze_all_action,
        ):
            freeze_actions.addAction(action)
        self.addMenu(self.keyframe_menu)
        self.addMenu(self.breakdown_menu)
        self.addMenu(self.mute_menu)
        self.addMenu(self.unmute_menu)
        self.addSeparator()
        self.addMenu(self.animation_copy_menu)
        self.addMenu(self.animation_paste_menu)
        self.addMenu(self.animation_cut_menu)
        self.addMenu(self.animation_delete_menu)
        self.addSeparator()
        self.addMenu(self.animation_layer_add_menu)
        self.addMenu(self.animation_layer_remove_menu)
        self.addSeparator()
        self.addMenu(self.align_menu)
        self.addMenu(self.copy_menu)
        self.addMenu(self.paste_menu)
        if self.child_set_action is not None:
            cast(_MenuActions, self).addAction(self.child_set_action)
        if self.rotation_set_action is not None:
            cast(_MenuActions, self).addAction(self.rotation_set_action)
        if self.rotation_menu is not None:
            self.addMenu(self.rotation_menu)
        if self.round_menu is not None:
            self.addMenu(self.round_menu)
        for xyz_menu in self.xyz_round_menus.values():
            self.addMenu(xyz_menu)
        self.addSeparator()
        self.addMenu(self.freeze_menu)


class AttributeRowWidget(qt.QWidget):
    """右揃えの属性名と入力Viewを並べ、詳細と操作を必要時に表示する。"""

    step_changed = qt.Signal(object)

    def __init__(
        self,
        row: ChannelRow,
        selection_count: int,
        parent: qt.QWidget,
        *,
        single_step: int | float | None = None,
        align_callback: Callable[[], None] | None = None,
        wheel_editing_without_focus: bool = False,
        context_menu_initializer: (
            Callable[[AttributeRowWidget], None] | None
        ) = None,
    ) -> None:
        """初期値を書き込まず、Bindingと表示部品を接続する。"""
        if type(wheel_editing_without_focus) is not bool:
            raise TypeError(
                "wheel_editing_without_focusにはboolを指定してください"
            )
        super().__init__(parent)
        self.row = row
        self.selection_count = selection_count
        self._align_callback = align_callback
        self.setObjectName(f"channel_{row.attribute.path}")
        self.name_label = _AttributeNameLabel(row.attribute.nice_name, self)
        self.name_label.setAlignment(
            qt.Qt.AlignmentFlag.AlignRight | qt.Qt.AlignmentFlag.AlignVCenter
        )
        self.input_indicator = _InputStateIndicator(self)
        self._context_menu: AttributeRowMenu | None = None
        self._context_menu_initializer = context_menu_initializer
        self._align_enabled = False
        self.editor = self._create_editor(
            single_step,
            wheel_editing_without_focus,
        )
        _use_row_context_menu(self.editor)
        # 入力グループを固定幅にし、余剰幅は属性名側へ配分する
        self.editor.setFixedWidth(_EDITOR_WIDTH)
        if isinstance(
            self.editor,
            (
                FloatSliderSpinBox,
                IntSliderSpinBox,
                FloatValueStepSpinBox,
                IntValueStepSpinBox,
            ),
        ):
            editor_layout = self.editor.layout()
            if isinstance(editor_layout, qt.QHBoxLayout):
                editor_layout.setSpacing(_FIELD_SPACING)
        if isinstance(
            self.editor, (FloatValueStepSpinBox, IntValueStepSpinBox)
        ):
            self.editor.settingsChanged.connect(self._notify_step_changed)

        # 値の混在と編集可能数はBindingの読み取り通知だけで更新する
        row.binding.state_changed.connect(self._update_state)
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_NAME_EDITOR_SPACING)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.input_indicator)
        layout.addWidget(self.editor)
        self._update_state()

    @property
    def context_menu(self) -> AttributeRowMenu:
        """初回参照時だけ全項目を生成・接続し、その後は同じメニューを返す。"""
        if self._context_menu is None:
            menu = AttributeRowMenu(self, self._align_values)
            self._context_menu = menu
            try:
                menu.align_action.setEnabled(self._align_enabled)
                if self._context_menu_initializer is not None:
                    self._context_menu_initializer(self)
            except Exception:
                self._context_menu = None
                menu.deleteLater()
                raise
        return self._context_menu

    @property
    def has_context_menu(self) -> bool:
        """メニューを生成せず、既に利用したか返す。"""
        return self._context_menu is not None

    def close_context_menu(self) -> None:
        """未使用のメニューを生成せず、表示中のものだけ閉じる。"""
        if self._context_menu is not None:
            self._context_menu.close()

    @property
    def freeze_separator_action(self) -> qt.QAction:
        """配置リセットで再生成される区切りを、現在のメニューから取得する。"""
        actions = self.context_menu.actions()
        freeze_action = self.context_menu.freeze_menu.menuAction()
        for previous, action in zip(actions, actions[1:]):
            if action == freeze_action and previous.isSeparator():
                return previous
        raise RuntimeError("フリーズメニュー直前の区切りがありません")

    def round_decimal_limit(self) -> int:
        """この行の値欄に現在表示している小数桁数を返す。"""
        if isinstance(
            self.editor, (FloatSliderSpinBox, FloatValueStepSpinBox)
        ):
            return self.editor.spin_box.decimals()
        raise RuntimeError("数値属性の行ではありません")

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """属性行のどこからでも共通の操作メニューを開く。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def _create_editor(
        self,
        single_step: int | float | None,
        wheel_editing_without_focus: bool,
    ) -> (
        BoolCheckBox
        | EnumComboBox
        | FloatSliderSpinBox
        | FloatValueStepSpinBox
        | IntValueStepSpinBox
        | IntSliderSpinBox
        | StringLineEdit
    ):
        """属性の種類と両側のhard limitから入力Viewを選ぶ。"""
        binding = self.row.binding
        if isinstance(binding, MayaBoolPlugsBinding):
            # ラベルを重複させず、入力列の左端にチェックを表示する
            return BoolCheckBox(binding, parent=self)
        if isinstance(binding, MayaEnumPlugsBinding):
            return EnumComboBox(
                binding,
                parent=self,
                wheel_requires_focus=not wheel_editing_without_focus,
            )
        if isinstance(binding, MayaStringPlugsBinding):
            return StringLineEdit(
                binding, parent=self, follow_source_during_edit=True
            )
        if isinstance(binding, MayaIntPlugsBinding):
            minimum, maximum = binding.hard_limits
            if (
                minimum is not None
                and maximum is not None
                and minimum < maximum
            ):
                integer_editor = IntSliderSpinBox(
                    binding,
                    self,
                    minimum=minimum,
                    maximum=maximum,
                    layout_order="value_slider",
                    value_select_all_on_mouse_focus=True,
                )
                integer_editor.spin_box.set_wheel_requires_focus(
                    not wheel_editing_without_focus
                )
                integer_editor.spin_box.setFixedWidth(_VALUE_FIELD_WIDTH)
                integer_editor.slider.setFixedWidth(_AUXILIARY_FIELD_WIDTH)
                return integer_editor
            return IntValueStepSpinBox(
                binding,
                self,
                single_step=(
                    1
                    if single_step is None
                    else _require_integer_step(single_step)
                ),
                step_mode="multiplicative",
                value_wheel_requires_focus=not wheel_editing_without_focus,
                step_wheel_requires_focus=not wheel_editing_without_focus,
                value_select_all_on_mouse_focus=True,
                step_select_all_on_mouse_focus=True,
                value_width=_VALUE_FIELD_WIDTH,
                step_width=_AUXILIARY_FIELD_WIDTH,
            )
        presentation = binding.view_model.presentation
        minimum, maximum = presentation.minimum, presentation.maximum
        decimals = get_channel_box_precision()
        if minimum is not None and maximum is not None and minimum < maximum:
            editor = FloatSliderSpinBox(
                binding,
                self,
                minimum=minimum,
                maximum=maximum,
                decimals=decimals,
                layout_order="value_slider",
                value_select_all_on_mouse_focus=True,
            )
            editor.spin_box.setUnitVisible(False)
            editor.spin_box.set_wheel_requires_focus(
                not wheel_editing_without_focus
            )
            editor.spin_box.setFixedWidth(_VALUE_FIELD_WIDTH)
            editor.slider.setFixedWidth(_AUXILIARY_FIELD_WIDTH)
            return editor
        # 属性名の特例を型の既定値より優先し、保存済みstepだけを上書きする
        default, mode, increment = self._step_defaults()
        value_editor = FloatValueStepSpinBox(
            binding,
            self,
            decimals=decimals,
            single_step=default if single_step is None else single_step,
            step_mode=mode,
            step_increment=increment,
            step_show_unit=False,
            value_wheel_requires_focus=not wheel_editing_without_focus,
            step_wheel_requires_focus=not wheel_editing_without_focus,
            value_select_all_on_mouse_focus=True,
            step_select_all_on_mouse_focus=True,
            value_width=_VALUE_FIELD_WIDTH,
            step_width=_AUXILIARY_FIELD_WIDTH,
        )
        value_editor.spin_box.setUnitVisible(False)
        return value_editor

    def set_wheel_editing_without_focus(self, enabled: bool) -> None:
        """値欄・Step欄・enumへ、未フォーカス時のホイール方針を反映する。"""
        if type(enabled) is not bool:
            raise TypeError("enabledにはboolを指定してください")
        requires_focus = not enabled
        editor = self.editor
        if isinstance(editor, EnumComboBox):
            editor.set_wheel_requires_focus(requires_focus)
        elif isinstance(editor, IntValueStepSpinBox):
            editor.spin_box.set_wheel_requires_focus(requires_focus)
            editor.step_spin_box.set_wheel_requires_focus(requires_focus)
        elif isinstance(editor, (FloatSliderSpinBox, IntSliderSpinBox)):
            editor.spin_box.set_wheel_requires_focus(requires_focus)
        elif isinstance(editor, FloatValueStepSpinBox):
            editor.spin_box.set_wheel_requires_focus(requires_focus)
            editor.step_spin_box.set_wheel_requires_focus(requires_focus)

    def _step_defaults(self) -> tuple[float, FloatStepMode, float]:
        """Slider以外の属性に、名前・型に応じた刻み幅を割り当てる。"""
        if self.row.attribute.name == "radius":
            return 0.1, "multiplicative", 1.0
        if self.row.attribute.kind == "angle":
            return 15.0, "additive", 15.0
        return 1.0, "multiplicative", 1.0

    def default_single_step(self) -> int | float:
        """属性名と型から決まる、保存設定を適用する前のStepを返す。"""
        return (
            1
            if isinstance(self.editor, IntValueStepSpinBox)
            else self._step_defaults()[0]
        )

    def _notify_step_changed(self) -> None:
        """現在のstepを通知し、Window側で属性ごとの設定を保持する。"""
        if isinstance(
            self.editor, (FloatValueStepSpinBox, IntValueStepSpinBox)
        ):
            self.step_changed.emit(self.editor.singleStep())

    def _update_state(self) -> None:
        """代表の接続・ロック色と混在を表示し、理由をtooltipへまとめる。"""
        binding = self.row.binding
        editable = binding.view_model.set_value_command.can_execute
        details = [self.row.attribute.nice_name, self.row.attribute.path]
        details.extend(
            (
                "表示・接続状態: 基準ノードのみ",
                f"適用候補: 選択中の{self.selection_count}ノード",
                "他ノードの編集可否と値の違いは、操作時に確認します",
            )
        )
        visible_targets = tuple(
            target
            for target in binding.target_states
            if target.is_available and target.input_state is not None
        )
        input_states: tuple[MayaPlugInputState, ...] = tuple(
            cast(MayaPlugInputState, target.input_state)
            for target in visible_targets
        )
        if input_states:
            representative = input_states[0]
            self.input_indicator.set_input_state(
                "locked" if visible_targets[0].is_locked else representative
            )
            details.append(
                "基準の接続状態: " + _INPUT_STATE_LABELS[representative]
            )
            if visible_targets[0].is_locked:
                details.append("基準のロック状態: ロックされています")
            if any(state != representative for state in input_states[1:]):
                counts = ", ".join(
                    f"{_INPUT_STATE_LABELS[state]} {input_states.count(state)}件"
                    for state in _INPUT_STATE_LABELS
                    if state in input_states
                )
                details.append("接続状態は選択ノード間で混在: " + counts)
            lock_states = tuple(target.is_locked for target in visible_targets)
            if any(locked != lock_states[0] for locked in lock_states[1:]):
                details.append("ロック状態は選択ノード間で混在")
        self.name_label.setText(self.row.attribute.nice_name)
        reasons = list(self.row.excluded)
        for target in binding.target_states:
            if target.edit_description:
                details.append(f"{target.name}: {target.edit_description}")
            if target.reason:
                reasons.append(f"{target.name}: {target.reason}")
        details.extend(reasons)
        defined = True
        if isinstance(binding, MayaEnumPlugsBinding):
            defined = binding.is_value_defined
            item = binding.definition.item_for_value(binding.value)
            details.append(
                f"基準値: {item.name} ({item.value})"
                if item is not None
                else f"基準値: 未定義 ({binding.value}) — 揃える操作はできません"
            )
            if not binding.definition.items:
                details.append("enumの選択肢がないため入力できません")
            details.append("他ノードのenum定義は、操作時に照合します")
        details.append("属性行を右クリック: 表示ノードの値に揃える")
        tooltip = "\n".join(details)
        self.name_label.setToolTip(tooltip)
        self.input_indicator.setToolTip(tooltip)
        self.editor.setToolTip(tooltip)
        can_align = self.selection_count > 1
        self._align_enabled = editable and can_align and defined
        if self._context_menu is not None:
            self._context_menu.align_action.setEnabled(self._align_enabled)

    def _align_values(self) -> None:
        """選択属性を明示した場合だけ、表示ノードの値へ揃える。"""
        if self._align_callback is not None:
            self._align_callback()
            return
        try:
            self.row.binding.apply_representative_value()
        except (ValueError, RuntimeError):
            # 拒否理由はBindingのedit_failedからWindowへ通知済み
            return


class AttributeStateRowWidget(qt.QWidget):
    """表示状態のラジオボタンとロックを余白なく横へ並べる。"""

    def __init__(
        self,
        row: ChannelStateRow,
        selection_count: int,
        parent: qt.QWidget,
        *,
        edit_session: MayaEditSession | None = None,
        display_state_request_handler: (
            Callable[[ChannelDisplayState], None] | None
        ) = None,
        lock_request_handler: Callable[[bool], None] | None = None,
    ) -> None:
        """状態の読取りと、単行・選択属性の明示入力を接続する。"""
        super().__init__(parent)
        self._edit_session = edit_session
        self._display_state_request_handler = display_state_request_handler
        self._lock_request_handler = lock_request_handler
        self.row = row
        self.selection_count = selection_count
        self.setObjectName(f"channel_state_{row.attribute.path}")
        self.name_label = _AttributeNameLabel(row.attribute.nice_name, self)
        self.name_label.setAlignment(
            qt.Qt.AlignmentFlag.AlignRight | qt.Qt.AlignmentFlag.AlignVCenter
        )
        self.editor = qt.QWidget(self)
        self.display_buttons: dict[ChannelDisplayState, qt.QRadioButton] = {}
        self._display_group = qt.QtWidgets.QButtonGroup(self.editor)
        self._display_group.setExclusive(True)
        controls = qt.QHBoxLayout(self.editor)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(_FIELD_SPACING)
        for value, label, description in _DISPLAY_OPTIONS:
            button = qt.QRadioButton(label, self.editor)
            button.setAutoExclusive(False)
            button.setAccessibleName(
                f"{row.attribute.nice_name} {description}"
            )
            self._display_group.addButton(button)
            self.display_buttons[value] = button
            controls.addWidget(button)
            button.clicked.connect(partial(self.set_display_state, value))
        self.lock_check_box: qt.QCheckBox = _LockCheckBox("lock", self.editor)
        self.lock_check_box.setTristate(False)
        self.lock_check_box.setAccessibleName(
            f"{row.attribute.nice_name} ロック"
        )
        controls.addWidget(self.lock_check_box)
        _use_row_context_menu(self.editor)
        # 操作部品に必要な幅だけを確保し、属性名へ残りを配分する
        self.editor.setFixedWidth(controls.sizeHint().width())
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_NAME_EDITOR_SPACING)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.editor)

        # 初期同期や外部変更は書き込まず、明示選択とクリックだけを入力にする
        self.lock_check_box.clicked.connect(self.set_locked)
        row.state_binding.state_changed.connect(self._update_state)
        self._update_state()

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """状態行の右クリックを受け止め、親画面のメニューも開かない。"""
        event.accept()

    def _update_state(self) -> None:
        """基準の表示状態と自身のlockだけを示し、操作別の可否を同期する。"""
        state = self.row.state_binding.state
        available = not self.row.state_binding.is_disposed
        old_display = tuple(
            button.blockSignals(True)
            for button in self.display_buttons.values()
        )
        old_lock = self.lock_check_box.blockSignals(True)
        # 表示同期はMayaへ書き戻さず、基準の状態だけを示す
        self._display_group.setExclusive(False)
        try:
            for value, button in self.display_buttons.items():
                button.setChecked(value == state.display_state)
                button.setEnabled(available and state.can_set_display)
            self.lock_check_box.setChecked(state.locked is True)
            self.lock_check_box.setEnabled(available and state.can_set_locked)
        finally:
            self._display_group.setExclusive(True)
            for button, blocked in zip(
                self.display_buttons.values(), old_display, strict=True
            ):
                button.blockSignals(blocked)
            self.lock_check_box.blockSignals(old_lock)

        self.name_label.setText(self.row.attribute.nice_name)
        details = [self.row.attribute.nice_name, self.row.attribute.path]
        details.append("表示・ロックは末尾の基準ノードの状態です")
        details.append(
            "対応する全選択ノードへ適用し、操作時に対象と変更可否を確認します"
        )
        details.append("全対象の混在や変更可能件数は常時計算しません")
        for target in state.targets[:1]:
            reasons = tuple(
                dict.fromkeys(
                    reason
                    for reason in (target.display_reason, target.lock_reason)
                    if reason
                )
            )
            if reasons:
                details.append(f"{target.plug_name}: {' / '.join(reasons)}")
        tooltip = "\n".join(details)
        self.name_label.setToolTip(tooltip)
        for value, _label, description in _DISPLAY_OPTIONS:
            self.display_buttons[value].setToolTip(
                f"{description}\n"
                "操作行が選択中なら、選択属性へ一括適用\n"
                f"左ドラッグで通過行だけをなぞり操作\n{tooltip}"
            )
        self.lock_check_box.setToolTip(
            "Lock: 属性自身のロック／解除\n"
            "基準がOFFなら全対象をロック、ONなら全対象を解除\n"
            "操作行が選択中なら、選択属性へ一括適用\n"
            "左ドラッグで開始時の操作を通過行だけへ適用\n"
            f"{tooltip}"
        )

    def set_display_state(
        self, value: ChannelDisplayState, _checked: bool = False
    ) -> None:
        """通常入力は選択属性へ、なぞり中はこの行だけへ適用する。"""
        try:
            session = self._edit_session
            if self._display_state_request_handler is not None:
                self._display_state_request_handler(value)
            else:
                self.row.state_binding.set_display_state(
                    value,
                    edit_session=(
                        session
                        if session is not None and session.is_editing
                        else None
                    ),
                )
        except (ValueError, RuntimeError, ExceptionGroup):
            # Bindingの通知で理由を表示し、操作後は正本の選択へ戻す
            pass
        finally:
            self._update_state()

    def set_locked(self, locked: bool) -> None:
        """通常入力は選択属性へ、なぞり中はこの行だけのlockを変える。"""
        try:
            session = self._edit_session
            if self._lock_request_handler is not None:
                self._lock_request_handler(locked)
            else:
                self.row.state_binding.set_locked(
                    locked,
                    edit_session=(
                        session
                        if session is not None and session.is_editing
                        else None
                    ),
                )
        except (ValueError, RuntimeError, ExceptionGroup):
            # Bindingの通知で理由を表示し、操作後は正本の状態へ戻す
            pass
        finally:
            self._update_state()


class _NodeNameLineEdit(StringLineEdit):
    """基準ノード名だけを、閲覧中はラベルに近い外観で表示する。"""

    def __init__(
        self, binding: MayaNodeNameBinding, parent: qt.QWidget
    ) -> None:
        """通常の入力外観の高さを保ち、状態変化に応じて背景を切り替える。"""
        super().__init__(binding, parent)
        self.setMinimumHeight(self.sizeHint().height())
        self._appearance_ready = True
        self.conflict_changed.connect(self._sync_appearance)
        self._sync_appearance()

    def focusInEvent(self, arg__1: qt.QtGui.QFocusEvent) -> None:
        """フォーカス時の正本更新後に、既定の入力外観を復元する。"""
        super().focusInEvent(arg__1)
        if qt.isValid(self):
            self._sync_appearance()

    def focusOutEvent(self, arg__1: qt.QtGui.QFocusEvent) -> None:
        """確定処理後に閲覧外観へ戻し、競合中の下書きは強調する。"""
        super().focusOutEvent(arg__1)
        if qt.isValid(self):
            self._sync_appearance()

    def setReadOnly(self, arg__1: bool) -> None:
        """名前ロックや参照状態の変化を、閲覧外観へ反映する。"""
        super().setReadOnly(arg__1)
        if getattr(self, "_appearance_ready", False):
            self._sync_appearance()

    def _sync_appearance(self, *_args: object) -> None:
        """編集可能なフォーカス中と競合中だけ既定の入力外観にする。"""
        editing = not self.isReadOnly() and (
            self.hasFocus() or self.hasConflict()
        )
        style = "" if editing else _NAME_IDLE_STYLE
        if self.styleSheet() != style:
            self.setStyleSheet(style)


class ChannelBoxWidget(qt.QWidget):
    """基準ノードの情報と、スクロール可能な属性入力欄を表示する。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """画面を作成してから選択監視を開始する。"""
        super().__init__(parent)
        self.custom_filter_registry = CustomFilterRegistry(self)
        self._dialog_anchor = DialogAnchorTracker(self)
        self.value_filter_preferences = ValueFilterPreferences()
        self.custom_filter_dialog: CustomFilterManagerDialog | None = None
        self._active_custom_filters: dict[str, CustomFilterSelection] = {}
        self._setup_mode_active = False
        self.step_profile = FloatStepProfile(self)
        self.int_step_profile = IntStepProfile(self)
        self._changing_steps = False
        self.row_widgets: tuple[
            AttributeRowWidget | AttributeStateRowWidget, ...
        ] = ()
        self.node_name_edit: StringLineEdit | None = None
        self._node_name_binding: MayaNodeNameBinding | None = None
        self._node_name_id: str | None = None
        self._scroll_anchor: tuple[str, int] | None = None
        self._table_node_ids: tuple[str, ...] = ()
        self._scroll_timer = qt.QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._restore_scroll_anchor)
        self._search_timer = qt.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search_filter)
        self.menu_bar = qt.QMenuBar(self)
        self.menu_bar.setNativeMenuBar(False)
        self.edit_menu = qt.QMenu("編集", self.menu_bar)
        self.menu_bar.addMenu(self.edit_menu)
        self.copy_menu = qt.QMenu("コピー", self.edit_menu)
        self.copy_all_values_action = qt.QAction("全属性", self)
        self.copy_all_values_action.setObjectName("copyAllValuesAction")
        self.copy_all_values_action.setToolTip(
            "基準ノードの対応する全属性値をOSクリップボードへコピー"
        )
        self.copy_all_values_action.setEnabled(False)
        self.copy_selected_values_action = qt.QAction("選択属性", self)
        self.copy_selected_values_action.setObjectName(
            "copySelectedValuesAction"
        )
        self.copy_selected_values_action.setToolTip(
            "基準ノードで選択中の属性値をOSクリップボードへコピー"
        )
        self.copy_selected_values_action.setEnabled(False)
        copy_actions = cast(_MenuActions, self.copy_menu)
        copy_actions.addAction(self.copy_selected_values_action)
        copy_actions.addAction(self.copy_all_values_action)
        self.edit_menu.addMenu(self.copy_menu)
        self.paste_menu = qt.QMenu("ペースト", self.edit_menu)
        self.paste_copied_values_actions: dict[
            ChannelAttributeFilter, qt.QAction
        ] = {}
        for display_filter, label, description in _PASTE_FILTER_OPTIONS:
            action = qt.QAction(f"コピー元と同じ属性：{label}", self)
            object_name = (
                "pasteCopiedValuesAction"
                if display_filter == "all"
                else "pasteCopiedValues"
                + "".join(part.title() for part in display_filter.split("_"))
                + "Action"
            )
            action.setObjectName(object_name)
            action.setToolTip(
                f"{description}選択ノードの同じ正式pathへ貼り付け"
            )
            action.setEnabled(False)
            self.paste_copied_values_actions[display_filter] = action
        self.paste_copied_values_action = self.paste_copied_values_actions[
            "all"
        ]
        self.paste_selected_values_action = qt.QAction("選択属性", self)
        self.paste_selected_values_action.setObjectName(
            "pasteSelectedValuesAction"
        )
        self.paste_selected_values_action.setToolTip(
            "コピーした値を選択属性へ貼り付け"
        )
        self.paste_selected_values_action.setEnabled(False)
        paste_actions = cast(_MenuActions, self.paste_menu)
        paste_actions.addAction(self.paste_selected_values_action)
        for action in self.paste_copied_values_actions.values():
            paste_actions.addAction(action)
        self.edit_menu.addMenu(self.paste_menu)
        self.settings_menu = qt.QMenu("設定", self.menu_bar)
        self.menu_bar.addMenu(self.settings_menu)
        self.wheel_editing_action = qt.QAction(
            "未フォーカス時のホイール編集", self
        )
        self.wheel_editing_action.setObjectName(
            "wheelEditingWithoutFocusAction"
        )
        self.wheel_editing_action.setCheckable(True)
        self.wheel_editing_action.setChecked(False)
        self.wheel_editing_action.setToolTip(
            "フォーカスのない値欄・Step欄・enum欄にマウスを重ねた状態で、"
            "ホイールによる値変更を有効にします。"
        )
        cast(_MenuActions, self.settings_menu).addAction(
            self.wheel_editing_action
        )
        self.search_visibility_menu = qt.QMenu(
            "検索欄の表示", self.settings_menu
        )
        self.search_visibility_group = qt.QActionGroup(self)
        self.search_visibility_group.setExclusive(True)
        self.search_visibility_actions: dict[_SearchVisibility, qt.QAction] = (
            {}
        )
        for value, label, tooltip in _SEARCH_VISIBILITY_OPTIONS:
            action = qt.QAction(label, self)
            action.setObjectName(
                "searchVisibility"
                + "".join(part.title() for part in value.split("_"))
                + "Action"
            )
            action.setCheckable(True)
            action.setChecked(value == "all_only")
            action.setToolTip(tooltip)
            self.search_visibility_group.addAction(action)
            cast(_MenuActions, self.search_visibility_menu).addAction(action)
            self.search_visibility_actions[value] = action
        self.settings_menu.addSeparator()
        self.settings_menu.addMenu(self.search_visibility_menu)
        self.manage_custom_filters_action = qt.QAction(
            "カスタムフィルター管理...", self
        )
        self.manage_custom_filters_action.setObjectName(
            "manageCustomFiltersAction"
        )
        cast(_MenuActions, self.settings_menu).addAction(
            self.manage_custom_filters_action
        )
        self.mode_combo = qt.QComboBox(self)
        self.mode_combo.addItem("値編集", "values")
        self.mode_combo.addItem("表示・ロック", "states")
        self.mode_combo.addItem(
            "カスタムフィルター設定", "custom_filter_setup"
        )
        self.mode_combo.setAccessibleName("表示モード")
        self.mode_combo.setToolTip(
            "どのモードも選択数に制限はなく、表示は末尾の基準ノードのみです。\n"
            "値編集・表示とロックは、対応する全選択ノードの属性へ適用します。\n"
            "カスタムフィルター設定は、基準ノードの型を編集します。"
        )
        self.filter_combo = qt.QComboBox(self)
        self._populate_filter_combo()
        self.filter_combo.setAccessibleName("属性の表示フィルター")
        self.filter_combo.setToolTip(
            "既定の5種類は末尾の基準ノードの表示状態で絞り込みます。\n"
            "Customは登録したJSONの属性pathを使用します。"
        )
        self.mode_label = qt.QLabel("Mode:", self)
        self.filter_label = qt.QLabel("Attribute Filter:", self)
        self.filter_fallback_label = qt.QLabel(self)
        self.filter_fallback_label.setObjectName("customFilterFallbackNotice")
        self.filter_fallback_label.setWordWrap(True)
        self.filter_fallback_label.hide()
        self.search_label = qt.QLabel("Attribute Search:", self)
        self.search_edit = qt.QLineEdit(self)
        self.search_edit.setObjectName("attributeSearchEdit")
        self.search_edit.setAccessibleName("属性名検索")
        self.search_edit.setPlaceholderText("属性名またはpathを検索")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip(
            "Nice Name・属性名・正式pathを、大文字小文字を区別せず検索します。\n"
            "空白で区切った語は、すべて含む属性だけを表示します。"
        )
        # 共通ヘッダーを検索欄から分離し、表示切替による列幅の変化を防ぐ
        controls_layout = qt.QGridLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.setColumnStretch(1, 1)
        for index, (label, control) in enumerate(
            (
                (self.mode_label, self.mode_combo),
                (self.filter_label, self.filter_combo),
            )
        ):
            label.setAlignment(
                qt.Qt.AlignmentFlag.AlignRight
                | qt.Qt.AlignmentFlag.AlignVCenter
            )
            label.setBuddy(control)
            control.setSizePolicy(
                qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Fixed
            )
            controls_layout.addWidget(label, index, 0)
            controls_layout.addWidget(control, index, 1)
        self.header_separator = qt.QFrame(self)
        self.header_separator.setObjectName("channelBoxHeaderSeparator")
        self.header_separator.setFrameShape(qt.QFrame.Shape.HLine)
        search_layout = qt.QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        self.search_label.setBuddy(self.search_edit)
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_edit, 1)
        self.header_label = qt.QLabel("ノードを選択してください", self)
        self.header_label.setTextInteractionFlags(
            qt.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.header_label.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Preferred
        )
        self.selection_count_label = qt.QLabel(self)
        self.selection_count_label.setObjectName("nodeSelectionCountLabel")
        self.selection_count_label.setAlignment(
            qt.Qt.AlignmentFlag.AlignCenter
        )
        self.selection_count_label.setFrameShape(qt.QFrame.Shape.StyledPanel)
        self.selection_count_label.setMargin(3)
        self.selection_count_label.setSizePolicy(
            qt.QSizePolicy.Policy.Fixed, qt.QSizePolicy.Policy.Preferred
        )
        self.selection_count_label.setFocusPolicy(qt.Qt.FocusPolicy.NoFocus)
        self.selection_count_label.hide()
        self.header_layout = qt.QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.addWidget(self.header_label)
        self.header_layout.addWidget(self.selection_count_label)
        self.context_menu = qt.QMenu(self)
        self.step_settings_menu = qt.QMenu("Step設定", self)
        self.reset_all_steps_action = qt.QAction(
            "初期値に戻す: 全ての属性", self
        )
        self.reset_all_steps_action.setObjectName(
            "resetAllAttributeStepsAction"
        )
        self.reset_all_steps_action.setToolTip(
            "保存した全属性のStep設定を削除して初期値へ戻す"
        )
        self.reset_selected_steps_action = qt.QAction(
            "初期値に戻す: 選択属性", self
        )
        self.reset_selected_steps_action.setObjectName(
            "resetSelectedAttributeStepsAction"
        )
        self.reset_selected_steps_action.setToolTip(
            "選択中でStep欄を持つ属性の保存設定を削除して初期値へ戻す"
        )
        step_actions = cast(_MenuActions, self.step_settings_menu)
        step_actions.addAction(self.reset_selected_steps_action)
        step_actions.addAction(self.reset_all_steps_action)
        self.context_menu.addMenu(self.step_settings_menu)
        self.message_label = qt.QLabel(self)
        self.message_label.setWordWrap(True)
        self.message_label.hide()
        self.table_view = ChannelTableView(self)
        self.scroll_area = self.table_view
        self.setup_panel = CustomFilterSetupPanel(
            self.custom_filter_registry,
            self,
            dialog_position=self._dialog_anchor.position,
        )
        self.setup_panel.create_requested.connect(self._create_filter_in_setup)
        self.setup_panel.manage_requested.connect(
            self._show_custom_filter_manager
        )
        self.preset_combo = self.setup_panel.preset_combo
        self.setup_panel.set_setup_mode(False)
        self.setup_panel.hide()
        self.empty_label = qt.QLabel("", self)
        self.empty_label.setWordWrap(True)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setMenuBar(self.menu_bar)
        layout.addLayout(controls_layout)
        layout.addWidget(self.header_separator)
        # 設定用の全体操作と、全モード共通のプリセット行を同じ場所で使う
        layout.addWidget(self.setup_panel.global_controls)
        layout.addWidget(self.setup_panel.preset_controls)
        layout.addLayout(search_layout)
        layout.addWidget(self.filter_fallback_label)
        layout.addLayout(self.header_layout)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.setup_panel, 1)
        layout.addWidget(self.message_label)

        # 選択・表示更新と、ユーザーによる値変更の経路を分離する
        self.controller = ChannelBoxController(self)
        self.table_view.selection_changed.connect(
            self._attribute_selection_changed
        )
        self.table_view.numeric_input_requested.connect(
            self._apply_numeric_input
        )
        self.table_view.numeric_input_rejected.connect(self._show_error)
        self.state_sweep = RadioButtonSweep(self.scroll_area)
        self.lock_sweep = CheckBoxSweep(self.scroll_area)
        for sweep in (self.state_sweep, self.lock_sweep):
            sweep.started.connect(self.controller.begin_state_edit)
            sweep.finished.connect(self.controller.state_edit_session.finish)
            self.controller.state_edit_session.finished.connect(sweep.finish)
        self.controller.rows_changed.connect(self._rebuild_rows)
        self.controller.selection_invalidated.connect(
            self._dispose_node_name_editor
        )
        self.controller.rows_about_to_change.connect(
            self._cancel_transient_input
        )
        self.controller.error_occurred.connect(self._show_error)
        self.controller.operation_reported.connect(self._show_operation_report)
        self.controller.mode_changed.connect(self._sync_mode)
        self.controller.filter_changed.connect(self._sync_filter)
        self.custom_filter_registry.path_changed.connect(
            self._custom_filter_path_changed
        )
        self.custom_filter_registry.changed.connect(
            self._custom_filters_changed
        )
        self.setup_panel.error_occurred.connect(self._show_error)
        self.controller.time_changed.connect(self._interrupt_value_input)
        self.mode_combo.currentIndexChanged.connect(self._change_mode)
        self.filter_combo.currentIndexChanged.connect(self._change_filter)
        self.copy_all_values_action.triggered.connect(self._copy_all_values)
        self.copy_selected_values_action.triggered.connect(
            self._copy_selected_values
        )
        for display_filter, action in self.paste_copied_values_actions.items():
            action.triggered.connect(
                partial(self._paste_copied_values, display_filter)
            )
        self.paste_selected_values_action.triggered.connect(
            self._paste_copied_values_to_selected
        )
        self.edit_menu.aboutToShow.connect(self._prepare_edit_menu)
        self.context_menu.aboutToShow.connect(self._prepare_step_settings_menu)
        self.step_settings_menu.aboutToShow.connect(
            self._prepare_step_settings_menu
        )
        self.reset_all_steps_action.triggered.connect(self._reset_all_steps)
        self.reset_selected_steps_action.triggered.connect(
            self._reset_selected_steps
        )
        self.step_profile.changed.connect(self._sync_step_profile)
        self.int_step_profile.changed.connect(self._sync_step_profile)
        self.wheel_editing_action.toggled.connect(
            self._set_wheel_editing_without_focus
        )
        for value, action in self.search_visibility_actions.items():
            action.toggled.connect(
                partial(self._change_search_visibility, value)
            )
        self.manage_custom_filters_action.triggered.connect(
            self._show_custom_filter_manager
        )
        self.search_edit.textChanged.connect(self._queue_search_filter)
        # 登録一覧が揃ってから値編集の選択を復元し、最初の属性一覧へ適用する
        initial_filter = self.value_filter_preferences.restore(
            self._active_custom_filters
        )
        if initial_filter == self.controller.attribute_filter:
            self._sync_filter()
            self.controller.refresh()
        else:
            self.controller.set_attribute_filter(initial_filter)

    def _populate_filter_combo(self) -> None:
        """既定の5件に続き、有効で正常な共有フィルターを登録順に並べる。"""
        self.filter_combo.clear()
        for label, value in _ATTRIBUTE_FILTER_OPTIONS:
            self.filter_combo.addItem(label, value)
        active: dict[str, CustomFilterSelection] = {}
        available = [
            entry
            for entry in self.custom_filter_registry.entries
            if entry.enabled and entry.definition is not None
        ]
        counts = Counter(
            entry.definition.name
            for entry in available
            if entry.definition is not None
        )
        for index, entry in enumerate(available, start=1):
            definition = entry.definition
            if definition is None:
                continue
            label = f"Custom: {definition.name}"
            if counts[definition.name] > 1:
                label += f" ({Path(entry.path).name}, {index})"
            selection = CustomFilterSelection(entry.path, definition)
            active[entry.path] = selection
            if not self._setup_mode_active:
                self.filter_combo.addItem(label, selection)
                self.filter_combo.setItemData(
                    self.filter_combo.count() - 1,
                    "定義ファイル: "
                    + entry.path
                    + "\n基準ノードの型に定義がない場合は、"
                    "keyable + channelbox へ戻ります。",
                    qt.Qt.ItemDataRole.ToolTipRole,
                )
        self._active_custom_filters = active

    def _custom_filter_path_changed(
        self, old_path: str, new_path: str
    ) -> None:
        """改名先へ選択を移し、一覧更新による標準フィルターへの復帰を防ぐ。"""
        if self.controller.is_disposed:
            return

        # 新pathの項目を先に用意し、controllerの通知を新しいComboBoxへ同期する
        blocked = self.filter_combo.blockSignals(True)
        try:
            self._populate_filter_combo()
        finally:
            self.filter_combo.blockSignals(blocked)
        selection = self._active_custom_filters.get(new_path)
        if selection is not None:
            self.controller.replace_custom_filter(
                selection, previous_path=old_path
            )
        self._sync_filter()

    def _custom_filters_changed(self) -> None:
        """登録変更を ComboBox と両モードの選択へ安全に反映する。"""
        if self.controller.is_disposed:
            return
        previous = self._active_custom_filters
        blocked = self.filter_combo.blockSignals(True)
        try:
            self._populate_filter_combo()
        finally:
            self.filter_combo.blockSignals(blocked)
        for path in previous.keys() - self._active_custom_filters.keys():
            self.controller.clear_custom_filter(path)
        for path, selection in self._active_custom_filters.items():
            if previous.get(path) != selection:
                self.controller.replace_custom_filter(selection)
        self._sync_filter()

    def _show_custom_filter_manager(self) -> None:
        """メニューと歯車の操作位置付近へ、同じ管理ウィンドウを表示する。"""
        click_position = self._dialog_anchor.position()
        dialog = self.custom_filter_dialog
        if dialog is None or not qt.isValid(dialog):
            dialog = CustomFilterManagerDialog(
                self.custom_filter_registry,
                self,
                confirm_create=self.setup_panel.confirm_leave,
                save_changes=self.setup_panel.save,
                discard_changes=self.setup_panel.discard,
                changes_pending=self.setup_panel.has_unsaved_changes,
                dialog_position=self._dialog_anchor.position,
            )
            self.setup_panel.changes_changed.connect(dialog.refresh_save_state)
            dialog.created.connect(self._edit_created_filter)
            dialog.rename_requested.connect(self._rename_managed_filter)
            self.custom_filter_dialog = dialog
        dialog.show_near(click_position)

    def _create_filter_in_setup(self) -> None:
        """設定画面内から、管理画面と同じ手順で新規JSONを作成する。"""
        position = self._dialog_anchor.position()
        if not self.setup_panel.confirm_leave(position):
            return
        draft = self.setup_panel.draft
        path = create_registered_filter(
            self,
            self.custom_filter_registry,
            reference_path=(
                draft.destination_path if draft is not None else None
            ),
            position=position,
        )
        if path is not None:
            self._edit_created_filter(path)

    def _edit_created_filter(self, path: str) -> None:
        """管理画面を開いたまま、新規定義を設定モードの編集対象にする。"""
        if self.controller.mode != "custom_filter_setup":
            self.controller.set_mode("custom_filter_setup")
        self.setup_panel.set_target(path)

    def _rename_managed_filter(self, path: str, position: qt.QPoint) -> None:
        """管理画面の選択ファイルを、共通の入力検証で改名する。"""
        self._edit_created_filter(path)
        self.setup_panel.rename_filter_at(position)

    def _set_wheel_editing_without_focus(self, enabled: bool) -> None:
        """表示中の全値入力行へ、メニューで選んだホイール方針を反映する。"""
        for widget in self.row_widgets:
            if isinstance(widget, AttributeRowWidget):
                widget.set_wheel_editing_without_focus(enabled)

    @property
    def search_visibility(self) -> _SearchVisibility:
        """検索欄の現在の表示方針を返す。"""
        for value, action in self.search_visibility_actions.items():
            if action.isChecked():
                return value
        return "all_only"

    def _change_search_visibility(
        self, value: _SearchVisibility, checked: bool
    ) -> None:
        """明示選択された検索欄の表示方針だけを反映する。"""
        if checked and value == self.search_visibility:
            self._sync_search_visibility()

    def _search_should_be_visible(self) -> bool:
        """設定と現在のAttribute Filterから検索欄の表示可否を返す。"""
        visibility = self.search_visibility
        return visibility == "always" or (
            visibility == "all_only"
            and self.controller.attribute_filter == "all"
        )

    def _sync_search_visibility(self) -> None:
        """検索欄を表示方針へ揃え、見えない検索条件を無効化する。"""
        visible = (
            not self._setup_mode_active and self._search_should_be_visible()
        )
        self.search_label.setVisible(visible)
        self.search_edit.setVisible(visible)
        self._search_timer.stop()
        self._apply_search_filter()

    def _queue_search_filter(self, _text: str) -> None:
        """連続する文字入力を同じQt event内でまとめて表示へ反映する。"""
        self._search_timer.start(0)

    def _search_tokens(self) -> tuple[str, ...]:
        """表示中の検索欄から、大文字小文字を区別しないAND条件を返す。"""
        if not self._search_should_be_visible():
            return ()
        return tuple(
            token.casefold()
            for token in self.search_edit.text().split()
            if token
        )

    def _apply_search_filter(self) -> None:
        """既存行とBindingを維持し、検索に一致するTable行だけを表示する。"""
        if self.controller.is_disposed:
            return
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.table_view.finish_numeric_edit(commit=True)
        tokens = self._search_tokens()
        visible_keys: list[tuple[str, str]] = []
        if tokens:
            for widget in self.row_widgets:
                attribute = widget.row.attribute
                searchable = " ".join(
                    (attribute.nice_name, attribute.name, attribute.path)
                ).casefold()
                if all(token in searchable for token in tokens):
                    visible_keys.append((attribute.path, attribute.kind))
        visible_count = self.table_view.set_visible_keys(
            visible_keys if tokens else None
        )
        self._update_empty_state(visible_count, searching=bool(tokens))

    def _change_mode(self, index: int) -> None:
        """編集中の値を通常のフォーカス移動で確定してから表示を切り替える。"""
        mode = self.mode_combo.itemData(index)
        if mode not in (
            "values",
            "values",
            "states",
            "custom_filter_setup",
        ):
            return
        if (
            self.controller.mode == "custom_filter_setup"
            and mode != "custom_filter_setup"
            and not self.setup_panel.confirm_leave()
        ):
            self._sync_mode()
            return
        self._prepare_view_change()
        self.controller.set_mode(mode)

    def _change_filter(self, index: int) -> None:
        """編集中の値を確定し、現在のモードのフィルターを切り替える。"""
        value = self.filter_combo.itemData(index)
        if isinstance(value, CustomFilterSelection):
            self._prepare_view_change()
            self.controller.set_attribute_filter(value)
            return
        if value in ("all", "visible", "keyable", "channel_box", "hidden"):
            self._prepare_view_change()
            self.controller.set_attribute_filter(value)

    def _prepare_view_change(self) -> None:
        """行の入力を確定し、再構築前のスクロール位置を保持する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.table_view.finish_numeric_edit(commit=True)
        focus_widget = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "focusWidget"),
        )
        focused = focus_widget()
        if focused is not None and self.table_view.isAncestorOf(focused):
            focused.clearFocus()
        self._remember_scroll_anchor()

    def _sync_mode(self) -> None:
        """controllerからのモード変更を属性へ入力せず表示へ反映する。"""
        setup = self.controller.mode == "custom_filter_setup"
        self._setup_mode_active = setup
        blocked = self.mode_combo.blockSignals(True)
        try:
            self.mode_combo.setCurrentIndex(
                self.mode_combo.findData(self.controller.mode)
            )
        finally:
            self.mode_combo.blockSignals(blocked)
        self.header_label.setVisible(not setup)
        if setup:
            self.context_menu.close()
            self.selection_count_label.hide()
        self.table_view.setVisible(not setup)
        self.empty_label.setVisible(not setup)
        self.setup_panel.setVisible(setup)
        self.setup_panel.set_setup_mode(setup)
        blocked = self.filter_combo.blockSignals(True)
        try:
            self._populate_filter_combo()
        finally:
            self.filter_combo.blockSignals(blocked)
        self._sync_filter()

    def _sync_filter(self) -> None:
        """モードごとのフィルター選択を再入力せずComboBoxへ反映する。"""
        selected = self.controller.attribute_filter
        if isinstance(selected, CustomFilterSelection):
            # QtのitemData比較はPython objectの同値より同一性を優先する場合がある
            index = next(
                (
                    index
                    for index in range(self.filter_combo.count())
                    if (
                        isinstance(
                            candidate := self.filter_combo.itemData(index),
                            CustomFilterSelection,
                        )
                        and candidate.path == selected.path
                    )
                ),
                -1,
            )
        else:
            index = self.filter_combo.findData(selected)
        blocked = self.filter_combo.blockSignals(True)
        try:
            self.filter_combo.setCurrentIndex(index)
        finally:
            self.filter_combo.blockSignals(blocked)
        self._sync_search_visibility()

        # 表示中のモードに関係なく値編集の保持値だけを保存する
        if not self.value_filter_preferences.save(
            self.controller.values_attribute_filter
        ):
            self._show_error(
                "値編集の属性フィルター選択を保存できませんでした"
            )

    def _sync_filter_fallback_notice(self) -> None:
        """カスタム定義に基準ノード型がない場合だけ代替条件を示す。"""
        node_type = self.controller.custom_filter_fallback_node_type
        self.filter_fallback_label.setText(
            f"{node_type} 型: keyable + channelbox（JSON に未定義）"
            if node_type is not None
            else ""
        )
        self.filter_fallback_label.setVisible(node_type is not None)

    def _remember_scroll_anchor(self) -> None:
        """表示先頭の属性pathを記録して、設定行の増減後も位置を保つ。"""
        self._scroll_anchor = next(
            (
                (w.row.attribute.path, w.y())
                for w in self.row_widgets
                if w.y() + w.height() > 0
            ),
            None,
        )

    def _restore_scroll_anchor(self) -> None:
        """同じ属性が残っている場合だけスクロール位置を復元する。"""
        anchor, self._scroll_anchor = self._scroll_anchor, None
        if anchor is None or self.controller.is_disposed:
            return
        path, offset = anchor
        for widget in self.row_widgets:
            if widget.row.attribute.path == path:
                self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().value()
                    + widget.y()
                    - offset
                )
                return

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """設定モード以外の余白からStep設定を開き、設定中は親への伝播も止める。"""
        if self.controller.mode != "custom_filter_setup":
            self.context_menu.popup(event.globalPos())
        event.accept()

    def refresh(self) -> None:
        """値を変更せず、現在のノードと属性を再取得する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.message_label.hide()
        self.controller.refresh()

    def _show_error(self, message: str) -> None:
        """入力拒否や再構築失敗を、操作対象の画面へ表示する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.message_label.setText(f"変更できませんでした: {message}")
        self.message_label.show()

    def _show_operation_report(self, message: str) -> None:
        """一括操作で対象外にした属性を通知し、理由がなければ表示を閉じる。"""
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))

    def _clear_message(self) -> None:
        """以前の操作通知を消して、現在の操作結果と混同させない。"""
        self.message_label.clear()
        self.message_label.hide()

    def _show_name_conflict(self, conflicted: bool) -> None:
        """外部改名と未確定入力の競合を、既存の通知欄へ示す。"""
        if conflicted:
            self.message_label.setText(_NAME_CONFLICT_MESSAGE)
            self.message_label.show()
        elif self.message_label.text() == _NAME_CONFLICT_MESSAGE:
            self._clear_message()

    def _dispose_node_name_editor(self) -> None:
        """旧ノードへフォーカス移動で書き込む前に名前入力を停止する。"""
        editor, self.node_name_edit = self.node_name_edit, None
        binding, self._node_name_binding = self._node_name_binding, None
        self._node_name_id = None
        if editor is not None and qt.isValid(editor):
            editor.setInputEnabled(False)
        if binding is not None:
            binding.dispose()
        if editor is not None and qt.isValid(editor):
            self.header_layout.removeWidget(editor)
            editor.hide()
            editor.deleteLater()
        self.header_label.show()
        self.selection_count_label.hide()

    def _sync_node_name_editor(self) -> None:
        """基準ノードの実体が変わった場合だけ名前入力欄を接続し直す。"""
        names = self.controller.node_names
        representative = self.controller.representative_node_name
        node_id = self.controller.node_ids[-1] if names else None
        binding = self._node_name_binding
        editor = self.node_name_edit
        if (
            representative is not None
            and node_id == self._node_name_id
            and binding is not None
            and not binding.is_disposed
            and editor is not None
            and qt.isValid(editor)
        ):
            binding.refresh()
        else:
            self._dispose_node_name_editor()
            if representative is not None and node_id is not None:
                # Mayaの一意なpathから取得し、選択末尾の実体だけを接続する
                binding = MayaNodeNameBinding(
                    Nodes().existing(representative), parent=self
                )
                try:
                    editor = _NodeNameLineEdit(binding, self)
                except Exception:
                    binding.dispose()
                    raise
                editor.setObjectName("nodeNameEdit")
                editor.setAccessibleName("基準ノード名")
                editor.edit_failed.connect(self._show_error)
                editor.conflict_changed.connect(self._show_name_conflict)
                self.header_layout.insertWidget(1, editor, 1)
                self.node_name_edit = editor
                self._node_name_binding = binding
                self._node_name_id = node_id
                self.header_label.hide()
        if representative is not None and self.node_name_edit is not None:
            selection_tooltip = (
                f"選択: {len(names)} ノード（末尾が基準）\n" + "\n".join(names)
            )
            if self.controller.mode == "values":
                selection_tooltip = (
                    "表示は基準ノードのみ。操作対象は各メニューの規則に従います\n"
                    + selection_tooltip
                )
            self.node_name_edit.setToolTip(selection_tooltip)
            if len(names) > 1:
                self.selection_count_label.setText(f"{len(names)} ノード")
                self.selection_count_label.setAccessibleName(
                    f"{len(names)} ノード選択中"
                )
                self.selection_count_label.setToolTip(selection_tooltip)
                self.selection_count_label.show()
            else:
                self.selection_count_label.hide()
        else:
            self.header_label.setText("ノードを選択してください")
            self.header_label.setToolTip("")
            self.selection_count_label.hide()

    def _attribute_selection_changed(self) -> None:
        """属性行の選択変更では、待機対象と古いドラッグ入力を終了する。"""
        was_editing = self.controller.value_edit_session.is_editing
        self.controller.finish_value_edit()
        if was_editing:
            self._interrupt_value_input(True)

    def _cancel_transient_input(self) -> None:
        """Bindingを破棄する前に、古い選択への入力とメニューを終了する。"""
        self._search_timer.stop()
        self.table_view.finish_numeric_edit(commit=False)
        self.context_menu.close()
        for widget in self.row_widgets:
            if isinstance(widget, AttributeRowWidget):
                widget.close_context_menu()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()

    def _interrupt_value_input(self, was_editing: bool) -> None:
        """時刻変更前のドラッグと未確定数値を、新しい時刻へ持ち越さない。"""
        self.table_view.finish_numeric_edit(commit=False)
        if was_editing:
            for widget in self.row_widgets:
                if isinstance(
                    widget.editor, (FloatSliderSpinBox, IntSliderSpinBox)
                ):
                    widget.editor.slider.finish_edit()

        # 再生中の全行走査を避け、フォーカス行に未確定文字がある場合だけ読む
        focused = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "focusWidget"),
        )()
        if focused is None or not self.isAncestorOf(focused):
            return
        owner: qt.QWidget | None = focused
        while owner is not None and not isinstance(owner, AttributeRowWidget):
            owner = cast(
                Callable[[], qt.QWidget | None], getattr(owner, "parentWidget")
            )()
        if owner is None:
            return
        editor = owner.editor
        if isinstance(editor, EnumComboBox):
            editor.hidePopup()
        if not isinstance(
            editor,
            (
                FloatValueStepSpinBox,
                FloatSliderSpinBox,
                IntValueStepSpinBox,
                IntSliderSpinBox,
            ),
        ):
            return
        spin_box = editor.spin_box
        children = cast(
            Callable[[type[qt.QLineEdit]], list[qt.QLineEdit]],
            getattr(spin_box, "findChildren"),
        )(qt.QLineEdit)
        if not any(child.isModified() for child in children):
            return
        binding = owner.row.binding
        assert isinstance(
            binding, (MayaFloatPlugsBinding, MayaIntPlugsBinding)
        )
        binding.refresh()
        # 入力通知を止めて再描画し、未確定文字だけを破棄する
        blocker = qt.QtCore.QSignalBlocker(spin_box)
        try:
            if isinstance(editor, (IntValueStepSpinBox, IntSliderSpinBox)):
                assert isinstance(binding, MayaIntPlugsBinding)
                editor.spin_box.setValue(binding.value)
            else:
                assert isinstance(binding, MayaFloatPlugsBinding)
                editor.spin_box.setValue(
                    binding.view_model.presentation.to_display(binding.value)
                )
        finally:
            del blocker

    def _request_int_value(self, key: tuple[str, str], value: int) -> bool:
        """整数の明示入力を選択中の数値属性へ適用する。"""
        try:
            self.controller.apply_numeric_values(self._action_keys(key), value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_int_step(
        self, key: tuple[str, str], editor: IntSpinBox, steps: int
    ) -> bool:
        """整数stepを選択中の各数値属性へ差分として適用する。"""
        try:
            self.controller.offset_numeric_values(
                self._action_keys(key), editor.singleStep() * steps
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_int_slider_value(
        self,
        key: tuple[str, str],
        editor: IntSliderSpinBox,
        value: int,
    ) -> bool:
        """整数Sliderを選択数値へ適用し、拒否時は全入力方式の操作を終了する。"""
        try:
            self.controller.apply_numeric_values(self._action_keys(key), value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
            editor.slider.finish_edit()
        return True

    def _apply_numeric_input(self, keys: object, value: float) -> None:
        """Qtの明示入力通知を受け、凍結した選択行へ一度だけ書き込む。"""
        selected = cast(tuple[tuple[str, str], ...], keys)
        try:
            self.controller.apply_numeric_values(selected, value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _request_numeric_value(
        self,
        key: tuple[str, str],
        binding: MayaFloatPlugsBinding,
        value: float,
    ) -> bool:
        """値欄の絶対値入力を、現在選択中の数値属性へ適用する。"""
        display_value = binding.view_model.presentation.to_display(value)
        try:
            self.controller.apply_numeric_values(
                self._action_keys(key), display_value
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_numeric_step(
        self,
        key: tuple[str, str],
        editor: FloatValueStepSpinBox | FloatSliderSpinBox,
        steps: int,
    ) -> bool:
        """操作元のStepによる共通増減量を、選択数値属性の現在値へ加える。"""
        display_offset = editor.spin_box.singleStep() * steps
        try:
            self.controller.offset_numeric_values(
                self._action_keys(key), display_offset
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_slider_value(
        self,
        key: tuple[str, str],
        binding: MayaFloatPlugsBinding,
        editor: FloatSliderSpinBox,
        value: float,
    ) -> bool:
        """Slider入力を選択数値へ適用し、拒否時は連続操作を終了する。"""
        display_value = binding.view_model.presentation.to_display(value)
        try:
            self.controller.apply_numeric_values(
                self._action_keys(key), display_value
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
            editor.slider.setSliderDown(False)
        return True

    def _request_bool_value(self, key: tuple[str, str], value: bool) -> bool:
        """選択中のbool属性を、操作したCheckBoxと同じ状態へ揃える。"""
        try:
            self.controller.apply_bool_values(self._action_keys(key), value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_enum_value(self, key: tuple[str, str], value: int) -> bool:
        """選択中で定義が一致するenum属性を、操作した項目へ揃える。"""
        try:
            keys = self._action_keys(key)
            self.controller.apply_enum_values(keys, key, value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_string_value(self, key: tuple[str, str], value: str) -> bool:
        """選択中のstring属性へ確定した文字列を適用する。"""
        try:
            self.controller.apply_string_values(self._action_keys(key), value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_display_state(
        self, key: tuple[str, str], state: ChannelDisplayState
    ) -> None:
        """単発は選択属性、なぞりは通過行だけを全対象へ適用する。"""
        try:
            session = self.controller.state_edit_session
            sweeping = session.is_editing
            self.controller.set_selected_display(
                (key,) if sweeping else self._action_keys(key),
                state,
                edit_session=session if sweeping else None,
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self.controller.state_edit_session.finish()
            self._show_error(str(error))

    def _request_locked(self, key: tuple[str, str], locked: bool) -> None:
        """単発は選択属性、なぞりは通過行だけを要求したlockへ揃える。"""
        try:
            session = self.controller.state_edit_session
            sweeping = session.is_editing
            self.controller.set_selected_locked(
                (key,) if sweeping else self._action_keys(key),
                locked,
                edit_session=session if sweeping else None,
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self.controller.state_edit_session.finish()
            self._show_error(str(error))

    def _begin_slider_edit(
        self, editor: FloatSliderSpinBox | IntSliderSpinBox
    ) -> None:
        """wheelは単発Undo、押下・キー操作は連続Undoとして開始する。"""
        self.controller.begin_value_edit(
            reuse_targets=not editor.slider.is_wheel_editing
        )

    def _finish_slider_edit(
        self, editor: FloatSliderSpinBox | IntSliderSpinBox
    ) -> None:
        """wheelの正常終了だけ、次の入力へ準備した対象を引き継ぐ。"""
        self.controller.finish_value_edit(
            retain_targets=editor.slider.is_wheel_editing and self.isVisible()
        )

    def _configure_value_input(
        self, widget: AttributeRowWidget, key: tuple[str, str]
    ) -> None:
        """既存Viewの入力を、属性選択を解釈する一括操作へ接続する。"""
        editor = widget.editor
        binding = widget.row.binding
        if isinstance(
            editor, (FloatValueStepSpinBox, FloatSliderSpinBox)
        ) and isinstance(binding, MayaFloatPlugsBinding):
            editor.spin_box.setValueRequestHandler(
                partial(self._request_numeric_value, key, binding)
            )
            editor.spin_box.setStepRequestHandler(
                partial(self._request_numeric_step, key, editor)
            )
            if isinstance(editor, FloatSliderSpinBox):
                editor.slider.setValueRequestHandler(
                    partial(self._request_slider_value, key, binding, editor)
                )
                editor.slider.editStarted.connect(
                    partial(self._begin_slider_edit, editor)
                )
                editor.slider.editFinished.connect(
                    partial(self._finish_slider_edit, editor)
                )
        elif isinstance(editor, (IntValueStepSpinBox, IntSliderSpinBox)):
            editor.spin_box.setValueRequestHandler(
                partial(self._request_int_value, key)
            )
            editor.spin_box.setStepRequestHandler(
                partial(self._request_int_step, key, editor.spin_box)
            )
            if isinstance(editor, IntSliderSpinBox):
                editor.slider.setValueRequestHandler(
                    partial(self._request_int_slider_value, key, editor)
                )
                editor.slider.editStarted.connect(
                    partial(self._begin_slider_edit, editor)
                )
                editor.slider.editFinished.connect(
                    partial(self._finish_slider_edit, editor)
                )
        elif isinstance(editor, BoolCheckBox):
            editor.setValueRequestHandler(
                partial(self._request_bool_value, key)
            )
        elif isinstance(editor, EnumComboBox):
            editor.setValueRequestHandler(
                partial(self._request_enum_value, key)
            )
        elif isinstance(editor, StringLineEdit):
            editor.setValueRequestHandler(
                partial(self._request_string_value, key)
            )

    def _action_keys(
        self, key: tuple[str, str]
    ) -> tuple[tuple[str, str], ...]:
        """選択内の行は全選択を対象にし、未選択行の操作はその行だけにする。"""
        selected = self.table_view.selected_keys()
        return selected if key in selected else (key,)

    def _run_selected_action(self, action: str, key: tuple[str, str]) -> None:
        """右クリックの明示操作を、入力部品と独立した選択編集入口へ渡す。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        selected = self._action_keys(key)
        try:
            if action == "align":
                self._clear_message()
                self.controller.align_selected_values(selected)
            elif action in ("key_selected", "breakdown_selected"):
                self._clear_message()
                self.controller.set_keyframes_selected(
                    selected, breakdown=action == "breakdown_selected"
                )
            elif action in ("mute_selected", "unmute_selected"):
                self._clear_message()
                self.controller.set_muted_selected(
                    selected, muted=action == "mute_selected"
                )
            elif action == "animation_copy_selected":
                self._clear_message()
                self.controller.copy_animation_curves_selected(selected)
            elif action == "animation_paste_selected":
                self._clear_message()
                self.controller.paste_animation_curves_to_selected(selected)
            elif action == "animation_cut_selected":
                self._clear_message()
                self.controller.cut_animation_curves_selected(selected)
            elif action == "animation_delete_selected":
                self._clear_message()
                self.controller.delete_animation_curves_selected(selected)
            elif action in (
                "animation_layer_add_selected",
                "animation_layer_remove_selected",
            ):
                self._clear_message()
                self.controller.edit_animation_layers_selected(
                    selected, add=action == "animation_layer_add_selected"
                )
            elif action == "copy_selected":
                self.controller.copy_selected_values(selected)
            elif action == "paste_selected":
                self._clear_message()
                self.controller.paste_copied_values_to_selected(selected)
            elif action in ("lock", "unlock"):
                self.controller.set_selected_locked(selected, action == "lock")
            elif action in ("keyable", "channel_box", "hidden"):
                self.controller.set_selected_display(selected, action)
            else:
                raise ValueError(f"未対応の選択操作です: {action}")
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _set_keyframes_all_keyable(self, breakdown: bool = False) -> None:
        """選択ノードの全Keyable属性に現在時刻の指定種別のキーを設定する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.set_keyframes_all_keyable(breakdown=breakdown)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _edit_animation_layers_all_keyable(self, add: bool) -> None:
        """選択ノードの全Keyable属性を選択レイヤへ追加・除去する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.edit_animation_layers_all_keyable(add=add)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _set_muted_all_visible(self, muted: bool) -> None:
        """各選択ノードのChannel Box表示属性を一括ミュート・解除する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.set_muted_all_visible(muted=muted)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _copy_animation_curves_all_visible(self) -> None:
        """各選択ノードのChannel Box表示属性の全時間の曲線をコピーする。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.copy_animation_curves_all_visible()
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _paste_animation_curves_same_attributes(self) -> None:
        """コピー元と同じ正式属性パスへ曲線を貼り付ける。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.paste_animation_curves_same_attributes()
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _cut_animation_curves_all_visible(self) -> None:
        """各選択ノードのChannel Box表示属性の全時間のキーをカットする。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.cut_animation_curves_all_visible()
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _delete_animation_curves_all_visible(self) -> None:
        """各選択ノードのChannel Box表示属性の全時間のキーを削除する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.delete_animation_curves_all_visible()
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _copy_selected_values(self) -> None:
        """基準nodeで選択中の属性値をOS clipboardへコピーする。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        try:
            self.controller.copy_selected_values(
                self.table_view.selected_keys()
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _copy_all_values(self) -> None:
        """基準nodeの対応する全属性値をOS clipboardへコピーする。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        try:
            self.controller.copy_all_values()
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _paste_copied_values(
        self, display_filter: ChannelAttributeFilter = "all"
    ) -> None:
        """OS clipboardの値を、表示条件で絞った同pathへ貼り付ける。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.paste_copied_values(display_filter)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _align_filtered_values(
        self, display_filter: ChannelAttributeFilter
    ) -> None:
        """表示ノードの属性状態に合う全属性を同ノードの値へ揃える。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.align_filtered_values(display_filter)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _prepare_round_menu(self, widget: AttributeRowWidget) -> None:
        """開いた数値行の表示桁数まで、各対象範囲の候補を遅延生成する。"""
        decimals = widget.round_decimal_limit()
        if widget.context_menu.round_menu_decimals == decimals:
            return
        for scope, submenu in widget.context_menu.round_scope_menus.items():
            submenu.clear()
            for digits in range(decimals + 1):
                label = (
                    "0（整数）"
                    if digits == 0
                    else f"0.{_ROUND_DIGIT_EXAMPLE[:digits]}"
                )
                item = qt.QAction(label, submenu)
                item.setObjectName(f"round_{scope}_{digits}")
                item.setToolTip(
                    f"各属性の現在の実値を小数{digits}桁へ四捨五入"
                )
                item.triggered.connect(
                    partial(self._round_values, widget, scope, digits)
                )
                cast(_MenuActions, submenu).addAction(item)
        widget.context_menu.round_menu_decimals = decimals

    def _round_values(
        self, widget: AttributeRowWidget, scope: _RoundScope, decimals: int
    ) -> None:
        """選択範囲内の各数値属性を現在値から個別に四捨五入する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            if scope == "selected":
                key = (widget.row.attribute.path, widget.row.attribute.kind)
                self.controller.round_selected_values(
                    self._action_keys(key), decimals
                )
            else:
                self.controller.round_filtered_values(scope, decimals)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _prepare_xyz_round_menu(self, widget: AttributeRowWidget) -> None:
        """開いた行の表示桁数に合わせてXYZ丸め候補を遅延生成する。"""
        decimals = widget.round_decimal_limit()
        if widget.context_menu.xyz_round_menu_decimals == decimals:
            return
        kind = widget.context_menu.xyz_round_kind
        if kind is None:
            return

        # 各子補償方法へ同じ桁数候補を設ける
        for (
            preserve_translation,
            child_attr,
        ), submenu in widget.context_menu.xyz_round_leaf_menus.items():
            submenu.clear()
            for digits in range(decimals + 1):
                label = (
                    "0（整数）"
                    if digits == 0
                    else f"0.{_ROUND_DIGIT_EXAMPLE[:digits]}"
                )
                item = qt.QAction(label, submenu)
                item.setObjectName(
                    f"round_{kind}_xyz_"
                    f"{'position_pose' if preserve_translation else 'pose'}_"
                    f"{child_attr}_{digits}"
                )
                item.setToolTip(
                    f"選択ノードの{kind}XYZを小数{digits}桁へ四捨五入"
                )
                item.triggered.connect(
                    partial(
                        self._round_transform_xyz,
                        kind,
                        digits,
                        preserve_translation,
                        child_attr,
                    )
                )
                cast(_MenuActions, submenu).addAction(item)
        widget.context_menu.xyz_round_menu_decimals = decimals

    def _round_transform_xyz(
        self,
        kind: RoundTransformKind,
        decimals: int,
        preserve_translation: bool,
        joint_child_compensation_attr: _JointChildCompensationAttr,
    ) -> None:
        """選択中の各Transform／Jointの指定XYZを子補償付きで丸める。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.round_transform_xyz(
                kind,
                decimals,
                compensate_child_translate=preserve_translation,
                joint_child_compensation_attr=joint_child_compensation_attr,
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _paste_copied_values_to_selected(self) -> None:
        """OS clipboardの項目数に応じた規則で選択属性へ貼り付ける。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.paste_copied_values_to_selected(
                self.table_view.selected_keys()
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _freeze_transforms(
        self, component: Literal["translate", "rotate", "scale", "all"]
    ) -> None:
        """選択中のtransform系ノードへ指定成分のフリーズを適用する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.freeze_transforms(component)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _consolidate_rotation(self, destination: RotationDestination) -> None:
        """選択中の各ノードの現在回転を指定属性へ集約する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        try:
            self.controller.consolidate_rotation(destination)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _open_rotation_set_window(
        self, initial_target: RotationDestination
    ) -> None:
        """右クリックした属性を初期設定先にして姿勢維持Windowを開く。"""
        from .. import bd_rotation_preserving_pose

        click_position = qt.QCursor.pos()
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        self.controller.state_edit_session.finish()
        self.controller.finish_value_edit()
        try:
            bd_rotation_preserving_pose.show(initial_target, click_position)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _open_child_compensated_set_window(
        self, initial_target: RoundTransformKind
    ) -> None:
        """右クリックした属性を初期設定先にして子補償Windowを開く。"""
        from .. import bd_child_compensated_set

        click_position = qt.QCursor.pos()
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self._clear_message()
        self.controller.state_edit_session.finish()
        self.controller.finish_value_edit()
        try:
            if initial_target == "translate":
                bd_child_compensated_set.show(
                    "translate", "translate", click_position
                )
            else:
                bd_child_compensated_set.show(
                    "rotation", initial_target, click_position
                )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _prepare_edit_menu(self) -> None:
        """現在のnode・行選択・clipboardに合わせて編集メニューを準備する。"""
        self._sync_edit_menu_actions()
        if self.controller.mode != "custom_filter_setup":
            self._set_paste_selected_tooltip(self.paste_selected_values_action)

    def _sync_edit_menu_actions(self) -> None:
        """clipboardの全量解析を行わず、非表示時も操作の有効性だけを更新する。"""
        if self.controller.mode == "custom_filter_setup":
            self.copy_all_values_action.setEnabled(False)
            self.copy_selected_values_action.setEnabled(False)
            self.paste_selected_values_action.setEnabled(False)
            for action in self.paste_copied_values_actions.values():
                action.setEnabled(False)
            return
        has_nodes = bool(self.controller.node_names)
        has_value_selection = self.controller.mode == "values" and bool(
            self.table_view.selected_keys()
        )
        can_paste = has_nodes and self.controller.can_paste_values()
        self.copy_all_values_action.setEnabled(has_nodes)
        self.copy_selected_values_action.setEnabled(
            has_nodes and has_value_selection
        )
        for action in self.paste_copied_values_actions.values():
            action.setEnabled(can_paste)
        self.paste_selected_values_action.setEnabled(
            can_paste and has_value_selection
        )

    def _set_paste_selected_tooltip(self, action: qt.QAction) -> None:
        """clipboardの項目数で変わる選択属性への貼り付け規則を説明する。"""
        action.setToolTip(
            "コピーした一つの値を選択属性へ貼り付け"
            if self.controller.can_paste_single_value()
            else "コピーした値から選択属性と同じ正式pathだけを貼り付け"
        )

    def _step_identity(
        self, key: tuple[str, str]
    ) -> tuple[str, FloatUnitKind] | None:
        """数値属性の選択keyを、永続化するStep識別子へ変換する。"""
        path, kind = key
        if kind not in ("number", "distance", "angle"):
            return None
        return path, kind

    def _int_step_identity(self, key: tuple[str, str]) -> str | None:
        """Maya固有の属性型と正式pathを汎用Profileの識別子へ変換する。"""
        path, kind = key
        return f"{kind}:{path}" if kind in ("byte", "short", "long") else None

    def _saved_single_step(self, key: tuple[str, str]) -> int | float | None:
        """属性keyに対応する保存済みStepを返す。"""
        integer_identity = self._int_step_identity(key)
        if integer_identity is not None:
            return self.int_step_profile.single_step(integer_identity)
        identity = self._step_identity(key)
        if identity is None:
            return None
        return self.step_profile.single_step(*identity)

    def _selected_step_identities(
        self,
    ) -> set[tuple[str, FloatUnitKind]]:
        """現在選択中でStep欄を持つ表示行の保存識別子を返す。"""
        selected = set(self.table_view.selected_keys())
        identities: set[tuple[str, FloatUnitKind]] = set()
        for widget in self.row_widgets:
            key = (widget.row.attribute.path, widget.row.attribute.kind)
            if (
                key not in selected
                or not isinstance(widget, AttributeRowWidget)
                or not isinstance(widget.editor, FloatValueStepSpinBox)
            ):
                continue
            identity = self._step_identity(key)
            if identity is not None:
                identities.add(identity)
        return identities

    def _selected_int_step_identities(self) -> set[str]:
        """選択中で整数Step欄を持つ行の保存識別子を返す。"""
        selected = set(self.table_view.selected_keys())
        identities: set[str] = set()
        for widget in self.row_widgets:
            if not isinstance(widget, AttributeRowWidget) or not isinstance(
                widget.editor, IntValueStepSpinBox
            ):
                continue
            key = (widget.row.attribute.path, widget.row.attribute.kind)
            identity = self._int_step_identity(key)
            if key in selected and identity is not None:
                identities.add(identity)
        return identities

    def _prepare_step_settings_menu(self) -> None:
        """保存済み設定と選択中のStep行に合わせてリセット可否を更新する。"""
        entries = self.step_profile.entries
        stored = {(entry.key, entry.unit_kind) for entry in entries}
        integer_stored = {entry.key for entry in self.int_step_profile.entries}
        self.reset_all_steps_action.setEnabled(bool(entries or integer_stored))
        self.reset_selected_steps_action.setEnabled(
            bool(
                stored.intersection(self._selected_step_identities())
                or integer_stored.intersection(
                    self._selected_int_step_identities()
                )
            )
        )

    def _reset_all_steps(self) -> None:
        """画面外を含む全ての保存済みStepを削除し、表示行を初期値へ戻す。"""
        self._clear_message()
        self.step_profile.clear()
        self.int_step_profile.clear()

    def _reset_selected_steps(self) -> None:
        """選択中でStep欄を持つ属性だけ、保存済みStepを削除する。"""
        identities = self._selected_step_identities()
        self._clear_message()
        self.step_profile.replace_entries(
            entry
            for entry in self.step_profile.entries
            if (entry.key, entry.unit_kind) not in identities
        )
        integer_identities = self._selected_int_step_identities()
        self.int_step_profile.replace_entries(
            entry
            for entry in self.int_step_profile.entries
            if entry.key not in integer_identities
        )

    def _sync_step_profile(self) -> None:
        """復元・リセットされたProfileを、表示中のStep欄へ書込みなしで反映する。"""
        if self._changing_steps:
            return
        self._changing_steps = True
        try:
            for widget in self.row_widgets:
                if not isinstance(
                    widget, AttributeRowWidget
                ) or not isinstance(
                    widget.editor, (FloatValueStepSpinBox, IntValueStepSpinBox)
                ):
                    continue
                key = (widget.row.attribute.path, widget.row.attribute.kind)
                saved = self._saved_single_step(key)
                value = (
                    widget.default_single_step() if saved is None else saved
                )
                if isinstance(widget.editor, IntValueStepSpinBox):
                    widget.editor.setSingleStep(_require_integer_step(value))
                else:
                    widget.editor.setSingleStep(value)
        finally:
            self._changing_steps = False
        self._prepare_step_settings_menu()

    def _prepare_row_menu(self, widget: AttributeRowWidget) -> None:
        """右クリックした行を選択対象に含め、全選択の状態でメニューを準備する。"""
        key = (widget.row.attribute.path, widget.row.attribute.kind)
        if key not in self.table_view.selected_keys():
            self.table_view.select_key(key)
        has_nodes = bool(self.controller.node_names)
        has_selection = bool(self.table_view.selected_keys())
        has_layers = bool(self.controller.selected_animation_layers())
        for menu, selected_action, all_action in (
            (
                widget.context_menu.animation_layer_add_menu,
                widget.context_menu.animation_layer_add_selected_action,
                widget.context_menu.animation_layer_add_all_keyable_action,
            ),
            (
                widget.context_menu.animation_layer_remove_menu,
                widget.context_menu.animation_layer_remove_selected_action,
                widget.context_menu.animation_layer_remove_all_keyable_action,
            ),
        ):
            menu.setEnabled(has_nodes and has_layers)
            selected_action.setEnabled(
                has_nodes and has_layers and has_selection
            )
            all_action.setEnabled(has_nodes and has_layers)
        selected = set(self.table_view.selected_keys())
        can_paste = has_nodes and self.controller.can_paste_values()
        can_paste_animation = (
            has_nodes and self.controller.can_paste_animation_curves()
        )
        widget.context_menu.animation_copy_selected_action.setEnabled(
            has_nodes and has_selection
        )
        widget.context_menu.animation_copy_all_action.setEnabled(has_nodes)
        widget.context_menu.animation_paste_same_action.setEnabled(
            can_paste_animation
        )
        widget.context_menu.animation_paste_selected_action.setEnabled(
            can_paste_animation and has_selection
        )
        widget.context_menu.animation_cut_selected_action.setEnabled(
            has_nodes and has_selection
        )
        widget.context_menu.animation_cut_all_action.setEnabled(has_nodes)
        widget.context_menu.animation_delete_selected_action.setEnabled(
            has_nodes and has_selection
        )
        widget.context_menu.animation_delete_all_action.setEnabled(has_nodes)
        widget.context_menu.copy_all_values_action.setEnabled(has_nodes)
        widget.context_menu.copy_selected_values_action.setEnabled(
            has_nodes and has_selection
        )
        for action in widget.context_menu.paste_copied_values_actions.values():
            action.setEnabled(can_paste)
        widget.context_menu.paste_selected_values_action.setEnabled(
            can_paste and has_selection
        )
        if widget.context_menu.round_menu is not None:
            widget.context_menu.round_scope_menus["selected"].setEnabled(
                any(
                    isinstance(row, ChannelRow)
                    and isinstance(row.binding, MayaFloatPlugsBinding)
                    and (row.attribute.path, row.attribute.kind) in selected
                    for row in self.controller.rows
                )
            )
        for xyz_menu in widget.context_menu.xyz_round_menus.values():
            xyz_menu.menuAction().setVisible(
                self.controller.has_transform_context()
            )
        if widget.context_menu.child_set_action is not None:
            widget.context_menu.child_set_action.setVisible(
                self.controller.can_set_child_compensated_value()
            )
        if widget.context_menu.rotation_set_action is not None:
            widget.context_menu.rotation_set_action.setVisible(
                self.controller.can_set_rotation_preserving_pose()
            )
        if widget.context_menu.rotation_menu is not None:
            widget.context_menu.rotation_menu.menuAction().setVisible(
                self.controller.can_consolidate_rotation()
            )
            widget.context_menu.rotation_actions["jointOrient"].setVisible(
                bool(
                    self.controller.representative_node_name
                    and cmds.nodeType(self.controller.representative_node_name)
                    == "joint"
                )
            )
        self._set_paste_selected_tooltip(
            widget.context_menu.paste_selected_values_action
        )
        show_freeze = self.controller.has_transform_context()
        widget.freeze_separator_action.setVisible(show_freeze)
        widget.context_menu.freeze_menu.menuAction().setVisible(show_freeze)
        widget.context_menu.freeze_translate_action.setEnabled(
            self.controller.can_freeze_translation()
        )
        widget.context_menu.align_action.setEnabled(
            any(
                isinstance(row, ChannelRow)
                and (row.attribute.path, row.attribute.kind) in selected
                and len(self.controller.node_names) > 1
                and row.binding.view_model.set_value_command.can_execute
                and (
                    not isinstance(row.binding, MayaEnumPlugsBinding)
                    or row.binding.is_value_defined
                )
                for row in self.controller.rows
            )
        )
        widget.context_menu.align_menu.setEnabled(
            len(self.controller.node_names) > 1
        )
        for action in widget.context_menu.align_filtered_actions.values():
            action.setEnabled(len(self.controller.node_names) > 1)
        self._prepare_step_settings_menu()

    def _add_selection_menu(self, widget: AttributeRowWidget) -> None:
        """値編集の行メニューに、選択属性の状態操作を追加する。"""
        key = (widget.row.attribute.path, widget.row.attribute.kind)
        menu = widget.context_menu
        menu.addSeparator()
        menu.addMenu(self.step_settings_menu)
        menu.addSeparator()
        for title, actions in (
            ("ロック", (("lock", "ロック"), ("unlock", "解除"))),
            (
                "表示",
                (
                    ("keyable", "Keyable"),
                    ("channel_box", "ChannelBox"),
                    ("hidden", "Hide"),
                ),
            ),
        ):
            group = qt.QMenu(title, menu)
            for action, label in actions:
                item = qt.QAction(label, group)
                item.setObjectName(f"selected_{action}")
                item.triggered.connect(
                    partial(self._run_selected_action, action, key)
                )
                cast(_MenuActions, group).addAction(item)
            menu.addMenu(group)
        menu.aboutToShow.connect(partial(self._prepare_row_menu, widget))

    def _connect_row_menu(self, widget: AttributeRowWidget) -> None:
        """初回生成時だけ、この行の全メニューを操作へ接続する。"""
        key = (widget.row.attribute.path, widget.row.attribute.kind)
        for (
            display_filter,
            action,
        ) in widget.context_menu.align_filtered_actions.items():
            action.triggered.connect(
                partial(
                    self._align_filtered_values,
                    display_filter,
                )
            )
        widget.context_menu.set_key_all_keyable_action.triggered.connect(
            partial(self._set_keyframes_all_keyable, False)
        )
        widget.context_menu.set_key_selected_action.triggered.connect(
            partial(self._run_selected_action, "key_selected", key)
        )
        widget.context_menu.set_breakdown_all_keyable_action.triggered.connect(
            partial(self._set_keyframes_all_keyable, True)
        )
        widget.context_menu.set_breakdown_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "breakdown_selected",
                key,
            )
        )
        widget.context_menu.mute_selected_action.triggered.connect(
            partial(self._run_selected_action, "mute_selected", key)
        )
        widget.context_menu.mute_all_animation_action.triggered.connect(
            partial(self._set_muted_all_visible, True)
        )
        widget.context_menu.unmute_selected_action.triggered.connect(
            partial(self._run_selected_action, "unmute_selected", key)
        )
        widget.context_menu.unmute_all_animation_action.triggered.connect(
            partial(self._set_muted_all_visible, False)
        )
        widget.context_menu.animation_copy_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "animation_copy_selected",
                key,
            )
        )
        widget.context_menu.animation_copy_all_action.triggered.connect(
            self._copy_animation_curves_all_visible
        )
        widget.context_menu.animation_paste_same_action.triggered.connect(
            self._paste_animation_curves_same_attributes
        )
        widget.context_menu.animation_paste_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "animation_paste_selected",
                key,
            )
        )
        widget.context_menu.animation_cut_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "animation_cut_selected",
                key,
            )
        )
        widget.context_menu.animation_cut_all_action.triggered.connect(
            self._cut_animation_curves_all_visible
        )
        widget.context_menu.animation_delete_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "animation_delete_selected",
                key,
            )
        )
        widget.context_menu.animation_delete_all_action.triggered.connect(
            self._delete_animation_curves_all_visible
        )
        widget.context_menu.copy_all_values_action.triggered.connect(
            self._copy_all_values
        )
        widget.context_menu.copy_selected_values_action.triggered.connect(
            partial(
                self._run_selected_action,
                "copy_selected",
                key,
            )
        )
        for (
            display_filter,
            action,
        ) in widget.context_menu.paste_copied_values_actions.items():
            action.triggered.connect(
                partial(
                    self._paste_copied_values,
                    display_filter,
                )
            )
        widget.context_menu.paste_selected_values_action.triggered.connect(
            partial(
                self._run_selected_action,
                "paste_selected",
                key,
            )
        )
        if widget.context_menu.round_menu is not None:
            widget.context_menu.round_menu.aboutToShow.connect(
                partial(self._prepare_round_menu, widget)
            )
        for xyz_menu in widget.context_menu.xyz_round_menus.values():
            xyz_menu.aboutToShow.connect(
                partial(self._prepare_xyz_round_menu, widget)
            )
        if (
            widget.context_menu.child_set_action is not None
            and widget.context_menu.xyz_round_kind is not None
        ):
            widget.context_menu.child_set_action.triggered.connect(
                partial(
                    self._open_child_compensated_set_window,
                    widget.context_menu.xyz_round_kind,
                )
            )
        if (
            widget.context_menu.rotation_set_action is not None
            and widget.context_menu.rotation_set_target is not None
        ):
            widget.context_menu.rotation_set_action.triggered.connect(
                partial(
                    self._open_rotation_set_window,
                    widget.context_menu.rotation_set_target,
                )
            )
        for (
            destination,
            action,
        ) in widget.context_menu.rotation_actions.items():
            action.triggered.connect(
                partial(self._consolidate_rotation, destination)
            )
        widget.context_menu.freeze_translate_action.triggered.connect(
            partial(self._freeze_transforms, "translate")
        )
        widget.context_menu.freeze_rotate_action.triggered.connect(
            partial(self._freeze_transforms, "rotate")
        )
        widget.context_menu.freeze_scale_action.triggered.connect(
            partial(self._freeze_transforms, "scale")
        )
        widget.context_menu.freeze_all_action.triggered.connect(
            partial(self._freeze_transforms, "all")
        )
        self._add_selection_menu(widget)
        widget.context_menu.animation_layer_add_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "animation_layer_add_selected",
                key,
            )
        )
        widget.context_menu.animation_layer_add_all_keyable_action.triggered.connect(
            partial(self._edit_animation_layers_all_keyable, True)
        )
        widget.context_menu.animation_layer_remove_selected_action.triggered.connect(
            partial(
                self._run_selected_action,
                "animation_layer_remove_selected",
                key,
            )
        )
        widget.context_menu.animation_layer_remove_all_keyable_action.triggered.connect(
            partial(self._edit_animation_layers_all_keyable, False)
        )

    def _rebuild_rows(self) -> None:
        """古いViewを破棄して、新しい選択の入力行を配置する。"""
        self.state_sweep.clear()
        self.lock_sweep.clear()
        for widget in self.row_widgets:
            if isinstance(widget, AttributeRowWidget):
                widget.close_context_menu()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()
            widget.hide()
        self.row_widgets = ()
        names = self.controller.node_names
        if self.controller.mode == "custom_filter_setup":
            self.setup_panel.show()
            self._dispose_node_name_editor()
            self.header_label.hide()
            self.selection_count_label.hide()
            self.table_view.set_rows([])
            self._table_node_ids = self.controller.node_ids
            node_name = self.controller.representative_node_name
            node_type = (
                cast(str, cmds.nodeType(node_name))
                if node_name is not None
                else None
            )
            self.setup_panel.set_node(
                node_name,
                node_type,
                self.controller.setup_attributes,
                display_filter=cast(
                    ChannelAttributeFilter, self.controller.attribute_filter
                ),
            )
            self.filter_fallback_label.hide()
            self.empty_label.hide()
            self._sync_edit_menu_actions()
            return
        self.table_view.show()
        self._sync_node_name_editor()
        widgets: list[AttributeRowWidget | AttributeStateRowWidget] = []
        try:
            for row in self.controller.rows:
                widget: AttributeRowWidget | AttributeStateRowWidget
                key = (row.attribute.path, row.attribute.kind)
                if isinstance(row, ChannelStateRow):
                    widget = AttributeStateRowWidget(
                        row,
                        len(names),
                        self.table_view.viewport(),
                        edit_session=self.controller.state_edit_session,
                        display_state_request_handler=partial(
                            self._request_display_state, key
                        ),
                        lock_request_handler=partial(
                            self._request_locked, key
                        ),
                    )
                    for value, button in widget.display_buttons.items():
                        self.state_sweep.add_button(
                            button,
                            on_change=partial(widget.set_display_state, value),
                            apply_unchanged=True,
                            group=value,
                        )
                    self.lock_sweep.add_button(
                        widget.lock_check_box,
                        on_change=widget.set_locked,
                        apply_unchanged=True,
                    )
                else:
                    widget = AttributeRowWidget(
                        row,
                        len(names),
                        self.table_view.viewport(),
                        context_menu_initializer=self._connect_row_menu,
                        single_step=self._saved_single_step(key),
                        align_callback=partial(
                            self._run_selected_action, "align", key
                        ),
                        wheel_editing_without_focus=(
                            self.wheel_editing_action.isChecked()
                        ),
                    )
                    widget.step_changed.connect(
                        partial(self._apply_step_value, key)
                    )
                    self._configure_value_input(widget, key)
                widgets.append(widget)
        except Exception:
            self.controller.dispose()
            raise
        self.row_widgets = tuple(widgets)
        self.table_view.set_rows(
            [
                TableRow(
                    key=(widget.row.attribute.path, widget.row.attribute.kind),
                    direct_numeric_input=self.controller.mode == "values",
                    widget=widget,
                    name_label=widget.name_label,
                    value_field=(
                        widget.editor.spin_box
                        if isinstance(
                            widget.editor,
                            (
                                FloatSliderSpinBox,
                                FloatValueStepSpinBox,
                                IntValueStepSpinBox,
                                IntSliderSpinBox,
                            ),
                        )
                        else None
                    ),
                    text_field=(
                        widget.editor
                        if isinstance(widget, AttributeRowWidget)
                        and isinstance(widget.editor, StringLineEdit)
                        else None
                    ),
                    input_indicator=(
                        widget.input_indicator
                        if isinstance(widget, AttributeRowWidget)
                        else None
                    ),
                    select_on_right_click=isinstance(
                        widget, AttributeRowWidget
                    ),
                )
                for widget in widgets
            ],
            preserve_selection=self._table_node_ids
            == self.controller.node_ids,
        )
        self._table_node_ids = self.controller.node_ids
        self._sync_filter_fallback_notice()
        self._sync_edit_menu_actions()
        self._apply_search_filter()
        # 行の配置が確定してから、残っている属性のスクロール位置を復元する
        self._scroll_timer.start(0)

    def _update_empty_state(
        self, visible_count: int, *, searching: bool
    ) -> None:
        """ノード・表示条件・検索結果の空状態を区別して表示する。"""
        if not self.controller.node_names:
            message = (
                "Maya ノードを選択すると、入力可能な種類の属性を表示します。"
            )
        elif not self.row_widgets:
            message = "フィルターに一致する bool・整数・float 系・enum・string 属性がありません。"
        elif searching and visible_count == 0:
            message = "検索条件に一致する属性がありません。"
        else:
            message = ""
        self.empty_label.setText(message)
        self.empty_label.setVisible(
            bool(message) and not self._setup_mode_active
        )

    def _apply_step_value(
        self, source_key: tuple[str, str], value: int | float
    ) -> None:
        """同じ表示stepを、選択中でStep欄を持つ属性へ反映して保持する。"""
        if self._changing_steps:
            return

        target_keys = set(self._action_keys(source_key))
        excluded: list[str] = []
        entries = {
            (entry.key, entry.unit_kind): entry
            for entry in self.step_profile.entries
        }
        integer_entries = {
            entry.key: entry for entry in self.int_step_profile.entries
        }
        planned: list[tuple[AttributeRowWidget, int | float]] = []
        # 型と範囲を全行で先に検証し、操作元が既に変わった場合も失敗時に戻す
        try:
            for widget in self.row_widgets:
                key = (widget.row.attribute.path, widget.row.attribute.kind)
                if key not in target_keys:
                    continue
                if not isinstance(
                    widget, AttributeRowWidget
                ) or not isinstance(
                    widget.editor, (FloatValueStepSpinBox, IntValueStepSpinBox)
                ):
                    excluded.append(
                        f"{widget.row.attribute.nice_name}: Step欄なし"
                    )
                    continue
                if isinstance(widget.editor, IntValueStepSpinBox):
                    checked = _require_integer_step(value)
                    integer_identity = self._int_step_identity(key)
                    assert integer_identity is not None
                    if checked == widget.default_single_step():
                        integer_entries.pop(integer_identity, None)
                    else:
                        integer_entries[integer_identity] = IntStepSetting(
                            integer_identity, checked
                        )
                    planned.append((widget, checked))
                else:
                    identity = self._step_identity(key)
                    assert identity is not None
                    setting = FloatStepSetting(identity[0], identity[1], value)
                    if value == widget.default_single_step():
                        entries.pop(identity, None)
                    else:
                        entries[identity] = setting
                    planned.append((widget, setting.single_step))
        except (TypeError, ValueError, OverflowError) as error:
            self._sync_step_profile()
            self._show_error(str(error))
            return
        self._changing_steps = True
        try:
            # 各行固有の増減方式は維持し、表示stepの数値だけを同期する
            for widget, checked in planned:
                if isinstance(widget.editor, IntValueStepSpinBox):
                    widget.editor.setSingleStep(_require_integer_step(checked))
                else:
                    assert isinstance(widget.editor, FloatValueStepSpinBox)
                    widget.editor.setSingleStep(checked)
            self.step_profile.replace_entries(entries.values())
            self.int_step_profile.replace_entries(integer_entries.values())
        finally:
            self._changing_steps = False

        self._prepare_step_settings_menu()
        self._show_operation_report(
            "対象外: " + " / ".join(excluded) if excluded else ""
        )

    def hideEvent(self, event: qt.QtGui.QHideEvent) -> None:
        """非表示になった時点で、待機中の数値対象も解放する。"""
        self.controller.finish_value_edit()
        super().hideEvent(event)

    def closeEvent(self, event: qt.QtGui.QCloseEvent) -> None:
        """閉じた画面へ対象とUndoの保持を持ち越さない。"""
        self.controller.finish_value_edit()
        super().closeEvent(event)

    def dispose(self) -> None:
        """画面の入力と監視を即時に終了する。"""
        self._dialog_anchor.dispose()
        if self.custom_filter_dialog is not None:
            self.custom_filter_dialog.close()
            self.custom_filter_dialog.deleteLater()
            self.custom_filter_dialog = None
        self._dispose_node_name_editor()
        self.state_sweep.dispose()
        self.lock_sweep.dispose()
        self._scroll_timer.stop()
        self._search_timer.stop()
        self.context_menu.close()
        self.setup_panel.order_context_menu.close()
        for widget in self.row_widgets:
            if isinstance(widget, AttributeRowWidget):
                widget.close_context_menu()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()
        self.controller.dispose()
        self.table_view.dispose()
