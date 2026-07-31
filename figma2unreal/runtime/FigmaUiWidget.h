// FigmaUiWidget.h — uespec.json → UMG 运行时解释器(视觉层)
//
// 架构约定:所有 CSS 风格字符串已由 scripts/ui_to_uespec.py 离线解析成强类型 uespec,
// 本类零解析逻辑,只按 uespec 用 WidgetTree 建 Widget 树。
//
// 目标引擎:UE 5.3+
// 依赖模块(Build.cs PublicDependencyModuleNames):"UMG","Slate","SlateCore","Json","JsonUtilities"
// 声明:本文件未在引擎内编译验证 —— 交付态 = 源码 + 集成说明(见 references/mapping.md)。
#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "Dom/JsonObject.h"
#include "FigmaUiWidget.generated.h"

class UCanvasPanel;
class UCanvasPanelSlot;
class UButton;
class UTextBlock;
class UWidget;

/** 每个已建元素的落位信息:所在父面板 + 面板内局部几何 + z(点击覆盖层按同几何叠按钮用)。 */
struct FFigmaElementSlot
{
	UCanvasPanel* ParentPanel = nullptr;
	FVector2D Pos = FVector2D::ZeroVector;
	FVector2D Size = FVector2D::ZeroVector;
	int32 ZOrder = 0;
};

/**
 * 把一份 <屏>.uespec.json 解释成 UMG Widget 树(根 UCanvasPanel,像素坐标 1:1)。
 * - 容器元素 → UCanvasPanel(+ 可选背景 UBorder/UImage 铺满)
 * - 纯色/圆角/描边 → UBorder(FSlateBrush RoundedBox:UE5 支持四角圆角 + 描边)
 * - 文字 → UBorder(对齐容器)+ UTextBlock
 * - 图片 → UImage(按约定路径 LoadObject,缺失回退透明 + UE_LOG)
 * 所有视觉 Widget 均 HitTestInvisible:点击一律走 AddClickOverlay 叠的透明 UButton。
 */
UCLASS(Blueprintable)
class UFigmaUiWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	/** 从 uespec.json 文件构建。相对路径视为相对 ProjectContentDir。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	bool BuildFromSpecFile(const FString& SpecFilePath);

	/**
	 * 从已解析的 uespec 构建。
	 * @param RootFilter 非空 = 只建这些根 id 及其子树(弹窗抽子树,对齐 render.js subtreeOf);
	 *                   被抽出的根用 absX/absY 摆放(与 HTML 版叠加语义一致)。
	 * @param bDrawStageBg 是否画帧背景(弹窗层不画)。
	 */
	bool BuildFromSpec(const TSharedPtr<FJsonObject>& Spec,
	                   const TArray<FString>& RootFilter = TArray<FString>(),
	                   bool bDrawStageBg = true);

	/** 按 figma node id 找已建 Widget(克隆行的 id 形如 "3:23#0")。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	UWidget* FindByFigmaId(const FString& Id) const;

	/** 改某文字元素内容(域内回填用,如已选服名)。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	void SetElementText(const FString& Id, const FText& NewText);

	/** 改某 UBorder 元素底色(checkbox 双态等)。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	void SetElementBrushColor(const FString& Id, const FLinearColor& Color);

	/**
	 * 在元素几何上叠一个全透明 UButton(命中区域=元素矩形),返回按钮供接线。
	 * 选择"叠透明按钮"而非 OnMouseButtonDown 的理由:不动已建视觉树、不自管坐标换算/
	 * 命中测试,UButton 自带按压/命中处理;视觉 Widget 全部 HitTestInvisible,
	 * 故按钮不会被视觉层挡住。
	 *
	 * ZOverride ≥ 0 时用它当 ZOrder,而不是默认的 元素z+10000 —— `@in:` 的弹窗内按钮
	 * 需要压过 `@any` 那层全帧点击层(30000),否则点不到。
	 */
	UButton* AddClickOverlay(const FString& ElementId, int32 ZOverride = -1);

	/** 在根画布任意矩形上叠透明按钮(@any / @panelOutside / 遮罩点击用)。 */
	UButton* AddRectOverlay(const FVector2D& Pos, const FVector2D& Size, int32 ZOrder);

	/** 在元素几何上叠一个居中 UTextBlock(checkbox 的勾号用),返回文本块。 */
	UTextBlock* AddTextOverlay(const FString& ElementId, const FText& InText,
	                           const FLinearColor& Color, float SizePx);

	/** 全帧半透明遮罩(弹窗 backdrop),ZOrder 压在内容之下。 */
	void AddBackdrop(const FLinearColor& Color);

	/**
	 * 列表行克隆(对齐 assemble.js renderRows):容器的直接子元素为模板行,
	 * 取第一行为模板、第二行 top 差为步长(无第二行则用行高);删掉模板行,
	 * 克隆 Count 份,第 i 份所有元素 id 记作 "<原id>#<i>"。
	 * @return 实际克隆行数(容器/模板缺失返回 0 并 UE_LOG)。
	 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	int32 CloneListRows(const FString& ContainerId, int32 Count);

	/** 克隆后第 Index 行的行根 id("<模板行id>#<Index>");容器或模板缺失返回空串。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	FString FindRowRootId(const FString& ContainerId, int32 Index) const;

	/** 查询元素落位(流程层给行叠按钮用)。 */
	bool GetElementSlot(const FString& Id, FFigmaElementSlot& Out) const;

	/** 帧尺寸(uespec 的 w/h)。 */
	FVector2D GetFrameSize() const { return FrameSize; }

	/** 素材根:img.path "_assets/a/b.png" → "<AssetRootPath>/a/b.b"(见 mapping.md)。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FigmaUi")
	FString AssetRootPath = TEXT("/Game/FigmaUi/Assets");

	/** 文本字体资产;未设回退引擎 Roboto。CJK 项目请指定含中文字形的字体(known-loss:字体族)。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FigmaUi")
	TObjectPtr<UObject> DefaultFontObject = nullptr;

	/** uespec 颜色数组 [r,g,b,a](rgb 0-255 sRGB、a 0-1)→ FLinearColor(流程层也用)。 */
	static FLinearColor ColorFromRgba(const TArray<TSharedPtr<FJsonValue>>* Rgba);

private:
	// ── 构建内部 ──
	void BuildElement(const TSharedPtr<FJsonObject>& El, UCanvasPanel* ParentPanel,
	                  const FVector2D& Pos, const FString& IdSuffix);
	UWidget* MakeVisualWidget(const TSharedPtr<FJsonObject>& El, const FVector2D& Size);
	UWidget* MakeTextWidget(const TSharedPtr<FJsonObject>& TextObj);
	UWidget* MakeImageWidget(const TSharedPtr<FJsonObject>& ImgObj, const FVector2D& Size);
	UWidget* MakeBoxWidget(const TSharedPtr<FJsonObject>& El);

	UCanvasPanelSlot* PlaceOnCanvas(UWidget* W, UCanvasPanel* Panel, const FVector2D& Pos,
	                                const FVector2D& Size, int32 ZOrder);
	static FLinearColor ColorFromField(const TSharedPtr<FJsonObject>& Obj, const FString& Field);
	FString AssetObjectPath(const FString& ImgPath) const;

	/** 根画布(BuildFromSpec 建)。 */
	UPROPERTY(Transient)
	TObjectPtr<UCanvasPanel> RootCanvas = nullptr;

	/** 保留 spec 供 CloneListRows 重建子树。 */
	TSharedPtr<FJsonObject> CachedSpec;

	UPROPERTY(Transient)
	TMap<FString, TObjectPtr<UWidget>> WidgetById;

	/** 容器元素 id → 其子面板(子元素挂这里)。 */
	UPROPERTY(Transient)
	TMap<FString, TObjectPtr<UCanvasPanel>> PanelById;

	// GC-OK: FFigmaElementSlot::ParentPanel 是**索引**不是持有 —— 所有面板都由
	// WidgetTree->ConstructWidget 建、归 UUserWidget::WidgetTree 所有(并镜像在上面的
	// UPROPERTY PanelById 里),且本表与 Widget 树同生共灭(BuildFromSpec 里 Empty、
	// CloneListRows 删行时同步 Remove),不会指向已被 GC 的对象。
	TMap<FString, FFigmaElementSlot> SlotById;
	TMap<FString, TArray<TSharedPtr<FJsonObject>>> ChildrenByParent;
	FVector2D FrameSize = FVector2D(1080.0, 1920.0);
};
