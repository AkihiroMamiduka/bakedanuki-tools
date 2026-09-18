# coding: utf-8
"""bdChannelBoxの表示順を調整する設定。"""

__all__ = ["ATTRIBUTE_PRIORITY_PATHS"]

# 上から順に優先表示する属性の正式な相対pathを指定する
# 順番の変更・追加・削除後はbd_tools.reload_package()で再読込みする
# 存在しない属性は飛ばし、重複したpathは最初の指定を使う
# 未指定属性はdrawOverride配下、その他の順とし、それぞれ元の相対順を保つ
ATTRIBUTE_PRIORITY_PATHS: tuple[str, ...] = (
    "visibility",
    "translate.translateX",
    "translate.translateY",
    "translate.translateZ",
    "rotate.rotateX",
    "rotate.rotateY",
    "rotate.rotateZ",
    "scale.scaleX",
    "scale.scaleY",
    "scale.scaleZ",
    "jointOrient.jointOrientX",
    "jointOrient.jointOrientY",
    "jointOrient.jointOrientZ",
    "rotateOrder",
    "rotateAxis.rotateAxisX",
    "rotateAxis.rotateAxisY",
    "rotateAxis.rotateAxisZ",
    "shear.shearXY",
    "shear.shearXZ",
    "shear.shearYZ",
    "rotatePivot.rotatePivotX",
    "rotatePivot.rotatePivotY",
    "rotatePivot.rotatePivotZ",
    "rotatePivotTranslate.rotatePivotTranslateX",
    "rotatePivotTranslate.rotatePivotTranslateY",
    "rotatePivotTranslate.rotatePivotTranslateZ",
    "scalePivot.scalePivotX",
    "scalePivot.scalePivotY",
    "scalePivot.scalePivotZ",
    "scalePivotTranslate.scalePivotTranslateX",
    "scalePivotTranslate.scalePivotTranslateY",
    "scalePivotTranslate.scalePivotTranslateZ",
    # drawOverride配下では有効化属性を先頭へ配置する
    "drawOverride.overrideEnabled",
)
