// FigmaUiWidget.cpp — uespec.json → UMG 运行时解释器(视觉层)实现
// 目标引擎:UE 5.3+;依赖模块:"UMG","Slate","SlateCore","Json","JsonUtilities"
// 声明:未在引擎内编译验证 —— 交付态 = 源码 + 集成说明(references/mapping.md)。
#include "FigmaUiWidget.h"

#include "Blueprint/WidgetTree.h"
#include "Components/Border.h"
#include "Components/Button.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/Image.h"
#include "Components/TextBlock.h"
#include "Engine/Texture2D.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Styling/SlateBrush.h"
#include "Styling/SlateTypes.h"

DEFINE_LOG_CATEGORY_STATIC(LogFigmaUi, Log, All);

// ── 小工具 ───────────────────────────────────────────────────────────────────

static double JNum(const TSharedPtr<FJsonObject>& O, const TCHAR* Field, double Def = 0.0)
{
	double V = Def;
	if (O.IsValid()) { O->TryGetNumberField(FString(Field), V); }
	return V;
}

static FString JStr(const TSharedPtr<FJsonObject>& O, const TCHAR* Field)
{
	FString V;
	if (O.IsValid()) { O->TryGetStringField(FString(Field), V); }
	return V;
}

FLinearColor UFigmaUiWidget::ColorFromRgba(const TArray<TSharedPtr<FJsonValue>>* Rgba)
{
	if (!Rgba || Rgba->Num() < 4)
	{
		return FLinearColor::Transparent;
	}
	// uespec 颜色 = [r,g,b,a],rgb 0-255(sRGB)、a 0-1;转线性色供 Slate 使用
	const uint8 R = (uint8)FMath::Clamp((*Rgba)[0]->AsNumber(), 0.0, 255.0);
	const uint8 G = (uint8)FMath::Clamp((*Rgba)[1]->AsNumber(), 0.0, 255.0);
	const uint8 B = (uint8)FMath::Clamp((*Rgba)[2]->AsNumber(), 0.0, 255.0);
	FLinearColor C = FLinearColor::FromSRGBColor(FColor(R, G, B, 255));
	C.A = (float)FMath::Clamp((*Rgba)[3]->AsNumber(), 0.0, 1.0);
	return C;
}

FLinearColor UFigmaUiWidget::ColorFromField(const TSharedPtr<FJsonObject>& Obj, const FString& Field)
{
	const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
	if (Obj.IsValid() && Obj->TryGetArrayField(Field, Arr))
	{
		return ColorFromRgba(Arr);
	}
	return FLinearColor::Transparent;
}

// ── 构建入口 ─────────────────────────────────────────────────────────────────

bool UFigmaUiWidget::BuildFromSpecFile(const FString& SpecFilePath)
{
	FString Path = SpecFilePath;
	if (FPaths::IsRelative(Path))
	{
		Path = FPaths::Combine(FPaths::ProjectContentDir(), Path);
	}
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Path))
	{
		UE_LOG(LogFigmaUi, Error, TEXT("uespec 文件读取失败: %s"), *Path);
		return false;
	}
	TSharedPtr<FJsonObject> Spec;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Spec) || !Spec.IsValid())
	{
		UE_LOG(LogFigmaUi, Error, TEXT("uespec JSON 解析失败: %s"), *Path);
		return false;
	}
	return BuildFromSpec(Spec);
}

bool UFigmaUiWidget::BuildFromSpec(const TSharedPtr<FJsonObject>& Spec,
                                   const TArray<FString>& RootFilter, bool bDrawStageBg)
{
	if (!Spec.IsValid() || !WidgetTree)
	{
		return false;
	}
	CachedSpec = Spec;
	WidgetById.Empty();
	PanelById.Empty();
	SlotById.Empty();
	ChildrenByParent.Empty();
	FrameSize = FVector2D(JNum(Spec, TEXT("w"), 1080.0), JNum(Spec, TEXT("h"), 1920.0));

	RootCanvas = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("FigmaRoot"));
	WidgetTree->RootWidget = RootCanvas;

	const TArray<TSharedPtr<FJsonValue>>* Els = nullptr;
	if (!Spec->TryGetArrayField(TEXT("els"), Els))
	{
		return false;
	}

	// 帧背景(弹窗层不画)
	const TSharedPtr<FJsonObject>* StageBg = nullptr;
	if (bDrawStageBg && Spec->TryGetObjectField(TEXT("stageBg"), StageBg))
	{
		TSharedPtr<FJsonObject> BgEl = MakeShared<FJsonObject>();
		const FString T = JStr(*StageBg, TEXT("type"));
		if (T == TEXT("image"))
		{
			TSharedPtr<FJsonObject> Img = MakeShared<FJsonObject>();
			Img->SetStringField(TEXT("path"), JStr(*StageBg, TEXT("path")));
			Img->SetStringField(TEXT("mode"), JStr(*StageBg, TEXT("mode")));
			BgEl->SetObjectField(TEXT("img"), Img);
		}
		else
		{
			BgEl->SetObjectField(TEXT("fill"), *StageBg); // solid / linear / radial(渐变走首停靠色回退)
		}
		if (UWidget* Bg = MakeVisualWidget(BgEl, FrameSize))
		{
			Bg->SetVisibility(ESlateVisibility::HitTestInvisible);
			PlaceOnCanvas(Bg, RootCanvas, FVector2D::ZeroVector, FrameSize, -10000);
		}
	}

	// 索引:parent → 子元素列表(uespec els 保持捕获顺序,即 z/绘制顺序)
	TArray<TSharedPtr<FJsonObject>> Ordered;
	for (const TSharedPtr<FJsonValue>& V : *Els)
	{
		const TSharedPtr<FJsonObject> El = V->AsObject();
		if (!El.IsValid())
		{
			continue;
		}
		Ordered.Add(El);
		ChildrenByParent.FindOrAdd(JStr(El, TEXT("parent"))).Add(El);
	}

	// 根集合:无过滤 = parent 为空的顶层;有过滤 = RootFilter 指定的根(用 absX/absY 摆放,
	// 对齐 render.js subtreeOf 的"根 parent 置空、几何仍是相对帧绝对 px"语义)
	for (const TSharedPtr<FJsonObject>& El : Ordered)
	{
		const FString Id = JStr(El, TEXT("id"));
		const bool bIsRoot = RootFilter.Num() > 0
			? RootFilter.Contains(Id)
			: JStr(El, TEXT("parent")).IsEmpty();
		if (bIsRoot)
		{
			BuildElement(El, RootCanvas,
			             FVector2D(JNum(El, TEXT("absX")), JNum(El, TEXT("absY"))), FString());
		}
	}
	return true;
}

void UFigmaUiWidget::BuildElement(const TSharedPtr<FJsonObject>& El, UCanvasPanel* ParentPanel,
                                  const FVector2D& Pos, const FString& IdSuffix)
{
	const FString OrigId = JStr(El, TEXT("id"));
	const FString Id = OrigId + IdSuffix;
	const FVector2D Size(JNum(El, TEXT("w")), JNum(El, TEXT("h")));
	const int32 Z = (int32)JNum(El, TEXT("z"));
	const TArray<TSharedPtr<FJsonObject>>* Kids = ChildrenByParent.Find(OrigId);

	UWidget* NodeWidget = nullptr;
	UCanvasPanel* OwnPanel = nullptr;
	if (Kids && Kids->Num() > 0)
	{
		// 容器:自身视觉铺满做背景,子元素按 localX/localY 挂进面板(对齐 render.js 嵌套)
		OwnPanel = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass());
		if (UWidget* Bg = MakeVisualWidget(El, Size))
		{
			Bg->SetVisibility(ESlateVisibility::HitTestInvisible);
			PlaceOnCanvas(Bg, OwnPanel, FVector2D::ZeroVector, Size, 0);
		}
		PanelById.Add(Id, OwnPanel);
		NodeWidget = OwnPanel;
	}
	else
	{
		NodeWidget = MakeVisualWidget(El, Size);
		if (!NodeWidget)
		{
			// 无任何视觉的叶子(如缺图矢量占位):透明占位保住 id 可寻址
			UBorder* Ph = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
			Ph->SetBrushColor(FLinearColor::Transparent);
			Ph->SetPadding(FMargin(0.f));
			NodeWidget = Ph;
		}
	}

	// 视觉层一律不可命中:点击全部走 AddClickOverlay 叠的透明按钮
	NodeWidget->SetVisibility(OwnPanel ? ESlateVisibility::SelfHitTestInvisible
	                                   : ESlateVisibility::HitTestInvisible);

	PlaceOnCanvas(NodeWidget, ParentPanel, Pos, Size, Z);

	const double Rot = JNum(El, TEXT("rot"));
	if (!FMath::IsNearlyZero(Rot))
	{
		NodeWidget->SetRenderTransformPivot(FVector2D(0.5f, 0.5f)); // 对齐 CSS transform-origin:center
		NodeWidget->SetRenderTransformAngle((float)Rot);
	}
	const double Opacity = JNum(El, TEXT("opacity"), 1.0);
	if (Opacity < 1.0)
	{
		NodeWidget->SetRenderOpacity((float)Opacity);
	}

	// known-loss:box-shadow / layer-blur 不渲染(见 mapping.md)
	const TArray<TSharedPtr<FJsonValue>>* Shadows = nullptr;
	if (El->TryGetArrayField(TEXT("shadow"), Shadows) && Shadows->Num() > 0)
	{
		UE_LOG(LogFigmaUi, Verbose, TEXT("[known-loss] box-shadow 未渲染: %s"), *Id);
	}
	const TSharedPtr<FJsonObject>* Blur = nullptr;
	if (El->TryGetObjectField(TEXT("blur"), Blur))
	{
		UE_LOG(LogFigmaUi, Verbose, TEXT("[known-loss] layer-blur 未渲染: %s"), *Id);
	}

	WidgetById.Add(Id, NodeWidget);
	FFigmaElementSlot SlotInfo;
	SlotInfo.ParentPanel = ParentPanel;
	SlotInfo.Pos = Pos;
	SlotInfo.Size = Size;
	SlotInfo.ZOrder = Z;
	SlotById.Add(Id, SlotInfo);

	if (Kids)
	{
		for (const TSharedPtr<FJsonObject>& Child : *Kids)
		{
			BuildElement(Child, OwnPanel,
			             FVector2D(JNum(Child, TEXT("localX")), JNum(Child, TEXT("localY"))),
			             IdSuffix);
		}
	}
}

// ── 视觉 Widget 工厂 ─────────────────────────────────────────────────────────

UWidget* UFigmaUiWidget::MakeVisualWidget(const TSharedPtr<FJsonObject>& El, const FVector2D& Size)
{
	const TSharedPtr<FJsonObject>* TextObj = nullptr;
	if (El->TryGetObjectField(TEXT("text"), TextObj))
	{
		return MakeTextWidget(*TextObj);
	}
	const TSharedPtr<FJsonObject>* ImgObj = nullptr;
	if (El->TryGetObjectField(TEXT("img"), ImgObj))
	{
		return MakeImageWidget(*ImgObj, Size);
	}
	const TSharedPtr<FJsonObject>* Fill = nullptr;
	const TSharedPtr<FJsonObject>* Border = nullptr;
	const TArray<TSharedPtr<FJsonValue>>* Radius = nullptr;
	const bool bHasFill = El->TryGetObjectField(TEXT("fill"), Fill);
	const bool bHasBorder = El->TryGetObjectField(TEXT("border"), Border);
	const bool bHasRadius = El->TryGetArrayField(TEXT("radius"), Radius);
	if (bHasFill || bHasBorder || bHasRadius)
	{
		return MakeBoxWidget(El);
	}
	return nullptr;
}

UWidget* UFigmaUiWidget::MakeTextWidget(const TSharedPtr<FJsonObject>& TextObj)
{
	UTextBlock* Tb = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
	Tb->SetText(FText::FromString(JStr(TextObj, TEXT("content"))));
	Tb->SetColorAndOpacity(FSlateColor(ColorFromField(TextObj, TEXT("rgba"))));

	FSlateFontInfo Font;
	UObject* FontObj = DefaultFontObject
		? DefaultFontObject.Get()
		: LoadObject<UObject>(nullptr, TEXT("/Engine/EngineFonts/Roboto.Roboto"));
	Font.FontObject = FontObj;
	// known-loss(字体族):family 不映射具体字体资产,统一 DefaultFontObject/Roboto;
	// weight 只分 Regular/Bold 两档(引擎 Roboto 的两个字面)
	const int32 Weight = (int32)JNum(TextObj, TEXT("weight"), 400);
	Font.TypefaceFontName = Weight >= 600 ? FName(TEXT("Bold")) : FName(TEXT("Regular"));
	const double SizePx = JNum(TextObj, TEXT("size"), 14.0);
	Font.Size = FMath::RoundToInt(SizePx * 0.75); // CSS px → Slate pt(96dpi 下 1pt = 4/3px)
	const double Ls = JNum(TextObj, TEXT("ls"));
	if (!FMath::IsNearlyZero(Ls) && SizePx > 0.0)
	{
		Font.LetterSpacing = FMath::RoundToInt(Ls / SizePx * 1000.0); // px → 1/1000 em
	}
	// 文字描边:FontOutline 近似 -webkit-text-stroke(渲染次序略异,见 mapping.md)
	const TSharedPtr<FJsonObject>* Stroke = nullptr;
	if (TextObj->TryGetObjectField(TEXT("stroke"), Stroke))
	{
		Font.OutlineSettings.OutlineSize = FMath::Max(1, FMath::RoundToInt(JNum(*Stroke, TEXT("width"), 1.0)));
		Font.OutlineSettings.OutlineColor = ColorFromField(*Stroke, TEXT("rgba"));
	}
	Tb->SetFont(Font);

	const FString Align = JStr(TextObj, TEXT("textAlign"));
	Tb->SetJustification(Align == TEXT("center") ? ETextJustify::Center
	                     : Align == TEXT("right") ? ETextJustify::Right
	                                              : ETextJustify::Left);
	const double Lh = JNum(TextObj, TEXT("lh"));
	if (Lh > 0.0 && SizePx > 0.0)
	{
		// 近似:UMG 行高是相对字号默认行距的倍率;CSS lh(px)/(size*1.2) ≈ 同视觉密度
		Tb->SetLineHeightPercentage((float)(Lh / (SizePx * 1.2)));
	}

	// 文本框内对齐(alignH/alignV)用 UBorder 的内容对齐实现(对齐 render.js 的 flex 布局)
	UBorder* Box = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
	Box->SetBrushColor(FLinearColor::Transparent);
	Box->SetPadding(FMargin(0.f));
	const FString AH = JStr(TextObj, TEXT("alignH"));
	Box->SetHorizontalAlignment(AH == TEXT("center") ? HAlign_Center
	                            : AH == TEXT("end") ? HAlign_Right
	                                                : HAlign_Left);
	const FString AV = JStr(TextObj, TEXT("alignV"));
	Box->SetVerticalAlignment(AV == TEXT("center") ? VAlign_Center
	                          : AV == TEXT("end") ? VAlign_Bottom
	                                              : VAlign_Top);
	Box->SetContent(Tb);
	return Box;
}

FString UFigmaUiWidget::AssetObjectPath(const FString& ImgPath) const
{
	// 约定:"_assets/s17/bg.png" → "<AssetRootPath>/s17/bg.bg"(导入 UE 后包名=文件名去扩展)
	FString Rel = ImgPath;
	Rel.RemoveFromStart(TEXT("_assets/"));
	const FString Dir = FPaths::GetPath(Rel);
	const FString Name = FPaths::GetBaseFilename(Rel);
	const FString Pkg = Dir.IsEmpty()
		? FString::Printf(TEXT("%s/%s"), *AssetRootPath, *Name)
		: FString::Printf(TEXT("%s/%s/%s"), *AssetRootPath, *Dir, *Name);
	return FString::Printf(TEXT("%s.%s"), *Pkg, *Name);
}

UWidget* UFigmaUiWidget::MakeImageWidget(const TSharedPtr<FJsonObject>& ImgObj, const FVector2D& Size)
{
	UImage* Img = WidgetTree->ConstructWidget<UImage>(UImage::StaticClass());
	const FString Path = JStr(ImgObj, TEXT("path"));
	const FString ObjPath = AssetObjectPath(Path);
	if (UTexture2D* Tex = LoadObject<UTexture2D>(nullptr, *ObjPath))
	{
		FSlateBrush Brush;
		Brush.SetResourceObject(Tex);
		Brush.ImageSize = Size;
		Brush.DrawAs = ESlateBrushDrawType::Image;
		Img->SetBrush(Brush);
		const FString Mode = JStr(ImgObj, TEXT("mode"));
		if (Mode != TEXT("stretch") && Mode != TEXT("cover"))
		{
			// cover 与 stretch 在"图片长宽比==元素长宽比"(figma 导出常态)下等价;
			// contain/tile 无原生对应 → 拉伸回退(known-loss,见 mapping.md)
			UE_LOG(LogFigmaUi, Verbose, TEXT("[known-loss] imgSize=%s 以拉伸回退: %s"), *Mode, *Path);
		}
	}
	else
	{
		Img->SetRenderOpacity(0.f); // 缺图回退透明,不平涂占位色
		UE_LOG(LogFigmaUi, Warning, TEXT("[known-loss] 贴图缺失,回退透明: %s(来自 %s)"), *ObjPath, *Path);
	}
	return Img;
}

UWidget* UFigmaUiWidget::MakeBoxWidget(const TSharedPtr<FJsonObject>& El)
{
	UBorder* B = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
	B->SetPadding(FMargin(0.f));

	FSlateBrush Brush;
	Brush.DrawAs = ESlateBrushDrawType::RoundedBox; // UE5:四角圆角 + 描边一体
	Brush.OutlineSettings.RoundingType = ESlateBrushRoundingType::FixedRadius;

	const TArray<TSharedPtr<FJsonValue>>* Radius = nullptr;
	if (El->TryGetArrayField(TEXT("radius"), Radius) && Radius->Num() == 4)
	{
		Brush.OutlineSettings.CornerRadii = FVector4(
			(*Radius)[0]->AsNumber(), (*Radius)[1]->AsNumber(),
			(*Radius)[2]->AsNumber(), (*Radius)[3]->AsNumber());
	}
	const TSharedPtr<FJsonObject>* Border = nullptr;
	if (El->TryGetObjectField(TEXT("border"), Border))
	{
		Brush.OutlineSettings.Width = (float)JNum(*Border, TEXT("width"), 1.0);
		Brush.OutlineSettings.Color = FSlateColor(ColorFromField(*Border, TEXT("rgba")));
	}

	FLinearColor FillColor = FLinearColor::Transparent;
	const TSharedPtr<FJsonObject>* Fill = nullptr;
	if (El->TryGetObjectField(TEXT("fill"), Fill))
	{
		const FString T = JStr(*Fill, TEXT("type"));
		if (T == TEXT("solid"))
		{
			FillColor = ColorFromField(*Fill, TEXT("rgba"));
		}
		else
		{
			// known-loss:linear/radial 渐变取首停靠色纯色回退;
			// 材质(UMaterialInterface 动态实例)方案为后续路线,见 mapping.md,不在本版实现
			const TArray<TSharedPtr<FJsonValue>>* Stops = nullptr;
			if ((*Fill)->TryGetArrayField(TEXT("stops"), Stops) && Stops->Num() > 0)
			{
				FillColor = ColorFromField((*Stops)[0]->AsObject(), TEXT("rgba"));
			}
			UE_LOG(LogFigmaUi, Warning, TEXT("[known-loss] %s 渐变以首停靠色回退: %s"),
			       *T, *JStr(El, TEXT("id")));
		}
	}
	Brush.TintColor = FSlateColor(FillColor);
	B->SetBrush(Brush);
	return B;
}

UCanvasPanelSlot* UFigmaUiWidget::PlaceOnCanvas(UWidget* W, UCanvasPanel* Panel, const FVector2D& Pos,
                                                const FVector2D& Size, int32 ZOrder)
{
	if (!W || !Panel)
	{
		return nullptr;
	}
	Panel->AddChild(W);
	UCanvasPanelSlot* S = Cast<UCanvasPanelSlot>(W->Slot);
	if (S)
	{
		S->SetAutoSize(false);
		S->SetPosition(Pos);
		S->SetSize(Size);
		S->SetZOrder(ZOrder);
	}
	return S;
}

// ── 查询 / 修改 ─────────────────────────────────────────────────────────────

UWidget* UFigmaUiWidget::FindByFigmaId(const FString& Id) const
{
	return WidgetById.FindRef(Id);
}

void UFigmaUiWidget::SetElementText(const FString& Id, const FText& NewText)
{
	UWidget* W = FindByFigmaId(Id);
	UTextBlock* Tb = Cast<UTextBlock>(W);
	if (!Tb)
	{
		if (UBorder* Box = Cast<UBorder>(W)) // GetContent 非 const,不能用 const 指针
		{
			Tb = Cast<UTextBlock>(Box->GetContent());
		}
	}
	if (Tb)
	{
		Tb->SetText(NewText);
	}
	else
	{
		UE_LOG(LogFigmaUi, Warning, TEXT("SetElementText:%s 不是文字元素"), *Id);
	}
}

void UFigmaUiWidget::SetElementBrushColor(const FString& Id, const FLinearColor& Color)
{
	if (UBorder* B = Cast<UBorder>(FindByFigmaId(Id)))
	{
		B->SetBrushColor(Color);
	}
	else
	{
		UE_LOG(LogFigmaUi, Warning, TEXT("SetElementBrushColor:%s 不是 UBorder"), *Id);
	}
}

bool UFigmaUiWidget::GetElementSlot(const FString& Id, FFigmaElementSlot& Out) const
{
	if (const FFigmaElementSlot* S = SlotById.Find(Id))
	{
		Out = *S;
		return true;
	}
	return false;
}

// ── 点击覆盖层 / 附加件 ──────────────────────────────────────────────────────

static void MakeButtonInvisible(UButton* Btn)
{
	FButtonStyle Style;
	FSlateBrush NoDraw;
	NoDraw.DrawAs = ESlateBrushDrawType::NoDrawType;
	Style.Normal = NoDraw;
	Style.Hovered = NoDraw;
	Style.Pressed = NoDraw;
	Style.Disabled = NoDraw;
	Style.NormalPadding = FMargin(0.f);
	Style.PressedPadding = FMargin(0.f);
	Btn->SetStyle(Style);
}

UButton* UFigmaUiWidget::AddClickOverlay(const FString& ElementId, int32 ZOverride)
{
	const FFigmaElementSlot* S = SlotById.Find(ElementId);
	if (!S || !S->ParentPanel)
	{
		UE_LOG(LogFigmaUi, Warning, TEXT("AddClickOverlay:事件元素未找到: %s"), *ElementId);
		return nullptr;
	}
	UButton* Btn = WidgetTree->ConstructWidget<UButton>(UButton::StaticClass());
	MakeButtonInvisible(Btn);
	// +10000:压在同面板所有视觉之上(视觉全部 HitTestInvisible,按钮独占命中)
	PlaceOnCanvas(Btn, S->ParentPanel, S->Pos, S->Size,
	              ZOverride >= 0 ? ZOverride : S->ZOrder + 10000);
	return Btn;
}

UButton* UFigmaUiWidget::AddRectOverlay(const FVector2D& Pos, const FVector2D& Size, int32 ZOrder)
{
	if (!RootCanvas)
	{
		return nullptr;
	}
	UButton* Btn = WidgetTree->ConstructWidget<UButton>(UButton::StaticClass());
	MakeButtonInvisible(Btn);
	PlaceOnCanvas(Btn, RootCanvas, Pos, Size, ZOrder);
	return Btn;
}

UTextBlock* UFigmaUiWidget::AddTextOverlay(const FString& ElementId, const FText& InText,
                                           const FLinearColor& Color, float SizePx)
{
	const FFigmaElementSlot* S = SlotById.Find(ElementId);
	if (!S || !S->ParentPanel)
	{
		return nullptr;
	}
	UTextBlock* Tb = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass());
	Tb->SetText(InText);
	Tb->SetColorAndOpacity(FSlateColor(Color));
	FSlateFontInfo Font;
	Font.FontObject = DefaultFontObject
		? DefaultFontObject.Get()
		: LoadObject<UObject>(nullptr, TEXT("/Engine/EngineFonts/Roboto.Roboto"));
	Font.TypefaceFontName = FName(TEXT("Bold"));
	Font.Size = FMath::RoundToInt(SizePx * 0.75f);
	Tb->SetFont(Font);
	Tb->SetJustification(ETextJustify::Center);

	UBorder* Box = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
	Box->SetBrushColor(FLinearColor::Transparent);
	Box->SetPadding(FMargin(0.f));
	Box->SetHorizontalAlignment(HAlign_Center);
	Box->SetVerticalAlignment(VAlign_Center);
	Box->SetContent(Tb);
	Box->SetVisibility(ESlateVisibility::HitTestInvisible);
	PlaceOnCanvas(Box, S->ParentPanel, S->Pos, S->Size, S->ZOrder + 5000);
	return Tb;
}

void UFigmaUiWidget::AddBackdrop(const FLinearColor& Color)
{
	if (!RootCanvas)
	{
		return;
	}
	UBorder* Bd = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass());
	Bd->SetBrushColor(Color);
	Bd->SetPadding(FMargin(0.f));
	Bd->SetVisibility(ESlateVisibility::HitTestInvisible);
	PlaceOnCanvas(Bd, RootCanvas, FVector2D::ZeroVector, FrameSize, -20000);
}

// ── 列表行克隆(对齐 assemble.js renderRows)──────────────────────────────────

static void CollectSubtreeIds(const FString& RootId,
                              const TMap<FString, TArray<TSharedPtr<FJsonObject>>>& ChildrenByParent,
                              TArray<FString>& Out)
{
	Out.Add(RootId);
	if (const TArray<TSharedPtr<FJsonObject>>* Kids = ChildrenByParent.Find(RootId))
	{
		for (const TSharedPtr<FJsonObject>& K : *Kids)
		{
			FString Kid;
			K->TryGetStringField(TEXT("id"), Kid);
			CollectSubtreeIds(Kid, ChildrenByParent, Out);
		}
	}
}

int32 UFigmaUiWidget::CloneListRows(const FString& ContainerId, int32 Count)
{
	const TArray<TSharedPtr<FJsonObject>>* Rows = ChildrenByParent.Find(ContainerId);
	UCanvasPanel* Panel = PanelById.FindRef(ContainerId);
	if (!Rows || Rows->Num() == 0 || !Panel)
	{
		UE_LOG(LogFigmaUi, Warning, TEXT("CloneListRows:容器或模板行缺失: %s"), *ContainerId);
		return 0;
	}
	const TSharedPtr<FJsonObject> Tpl = (*Rows)[0];
	const double BaseX = JNum(Tpl, TEXT("localX"));
	const double BaseY = JNum(Tpl, TEXT("localY"));
	const double Step = Rows->Num() > 1
		? JNum((*Rows)[1], TEXT("localY")) - BaseY
		: JNum(Tpl, TEXT("h"), 104.0);

	// 删模板行(含子树的 Widget 与映射项)
	for (const TSharedPtr<FJsonObject>& Row : *Rows)
	{
		TArray<FString> Ids;
		CollectSubtreeIds(JStr(Row, TEXT("id")), ChildrenByParent, Ids);
		for (const FString& Rid : Ids)
		{
			if (UWidget* W = WidgetById.FindRef(Rid))
			{
				W->RemoveFromParent();
			}
			WidgetById.Remove(Rid);
			PanelById.Remove(Rid);
			SlotById.Remove(Rid);
		}
	}

	// 克隆:统一以第一行为模板(对齐 assemble.js),行 i 的所有元素 id = "<原id>#<i>"
	for (int32 i = 0; i < Count; ++i)
	{
		BuildElement(Tpl, Panel, FVector2D(BaseX, BaseY + Step * i),
		             FString::Printf(TEXT("#%d"), i));
	}
	return Count;
}

FString UFigmaUiWidget::FindRowRootId(const FString& ContainerId, int32 Index) const
{
	const TArray<TSharedPtr<FJsonObject>>* Rows = ChildrenByParent.Find(ContainerId);
	if (!Rows || Rows->Num() == 0)
	{
		return FString();
	}
	FString TplId;
	(*Rows)[0]->TryGetStringField(TEXT("id"), TplId);
	if (TplId.IsEmpty())
	{
		return FString();
	}
	const FString RowId = FString::Printf(TEXT("%s#%d"), *TplId, Index);
	return WidgetById.Contains(RowId) ? RowId : FString();
}
