// FigmaFlowComponent.h — flow.uespec.json → 交互流程解释器(assemble.js 语义的 UE 版)
//
// 语义对齐 figma2html/runtime/assemble.js:
//   底屏常驻(base)+ 弹窗叠加(modal = 抽子树 + 半透明 backdrop,非 swap)、
//   click 事件(守卫 guard / toggleFlag / send / openModal / closeModal)、
//   列表行克隆(renderRows)、checkbox 双态绑定;域内语义(数据→行、回填)走 IFigmaAppHook。
//
// 目标引擎:UE 5.3+
// 依赖模块(Build.cs PublicDependencyModuleNames):"UMG","Slate","SlateCore","Json","JsonUtilities"
// 声明:本文件未在引擎内编译验证 —— 交付态 = 源码 + 集成说明(见 references/mapping.md)。
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Dom/JsonObject.h"
#include "UObject/Interface.h"
#include "FigmaFlowComponent.generated.h"

class UFigmaUiWidget;
class UFigmaFlowComponent;
class UButton;
class UTextBlock;
class APlayerController;

// ── 域内 hook(对齐 figma2html app.js 的 APPHOOK 分工:引擎管结构与机制,app 管域内语义)──
UINTERFACE(MinimalAPI, Blueprintable)
class UFigmaAppHook : public UInterface
{
	GENERATED_BODY()
};

class IFigmaAppHook
{
	GENERATED_BODY()

public:
	/** 流程构建完成(可在此拉数据、PopulateList、回填文案)。 */
	UFUNCTION(BlueprintNativeEvent, Category = "FigmaUi")
	void OnFlowReady();

	/** do:"send" 的动作出口(如 "Enter" → 发登录协议)。 */
	UFUNCTION(BlueprintNativeEvent, Category = "FigmaUi")
	void OnSend(const FString& Action);

	/** 守卫失败(如未勾协议就点开始)。 */
	UFUNCTION(BlueprintNativeEvent, Category = "FigmaUi")
	void OnGuardFail(const FString& DoName);

	/** flow 里出现的非内置 do 名。 */
	UFUNCTION(BlueprintNativeEvent, Category = "FigmaUi")
	void OnCustomAction(const FString& DoName, const FString& Arg);

	/** 列表行被点(行号 = PopulateList 的克隆序)。 */
	UFUNCTION(BlueprintNativeEvent, Category = "FigmaUi")
	void OnListRowClicked(int32 RowIndex);

	/** state 里某键变化(toggleFlag / SetStateString 之后)。 */
	UFUNCTION(BlueprintNativeEvent, Category = "FigmaUi")
	void OnStateChanged(const FString& Key);
};

/** UButton::OnClicked 无 sender 参数,用代理对象携带事件/行号路由回组件。 */
UCLASS()
class UFigmaClickProxy : public UObject
{
	GENERATED_BODY()

public:
	UPROPERTY()
	TObjectPtr<UFigmaFlowComponent> Owner;

	int32 EventIndex = -1; // >=0:flow 事件序号
	int32 RowIndex = -1;   // >=0:列表行号
	                       // 两者都 -1:纯"吞点击"盾(@panelOutside 的面板保护层)

	UFUNCTION()
	void HandleClick();
};

/** flow 事件的强类型运行时形态(uespec 已结构化,这里只是再落成 C++ 结构)。 */
struct FFigmaFlowTarget
{
	FString Kind;  // "node" / "any" / "panelOutside" / "in"
	FString Id;    // kind==node / in
	FString Modal; // kind==any / panelOutside / in
};

struct FFigmaFlowEvent
{
	FString On;
	TArray<FFigmaFlowTarget> Targets;
	TArray<FString> Guard;
	FString Do;
	FString Arg;
};

/**
 * 挂在任意 Actor(常见:PlayerController 拥有的 HUD Actor)上;InitFlow 后:
 * base 屏 AddToViewport(0) 常驻,各 modal 屏(抽子树+backdrop)AddToViewport(50+i) 初始隐藏。
 * 事件接线方式 = 透明 UButton 覆盖层(理由见 UFigmaUiWidget::AddClickOverlay 注释)。
 */
UCLASS(ClassGroup = (FigmaUi), meta = (BlueprintSpawnableComponent))
class UFigmaFlowComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	/** uespec 所在目录,相对 ProjectContentDir(见 mapping.md 集成步骤)。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FigmaUi")
	FString SpecDirectory = TEXT("FigmaUi/Spec");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FigmaUi")
	FString FlowFileName = TEXT("flow.uespec.json");

	/** 域内 hook 实现者(蓝图或 C++ 实现 IFigmaAppHook)。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FigmaUi")
	TScriptInterface<IFigmaAppHook> AppHook;

	/** 读 flow.uespec.json + 各屏 uespec,建 UI、接事件。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	bool InitFlow(APlayerController* OwningPlayer);

	// ── 内置动作(蓝图也可直接调)──
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	void OpenModal(const FString& Name);

	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	void CloseModal();

	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	void ToggleFlag(const FString& Flag);

	/** 域内回填 state(如选服后 selected=服 id;空串视为"未选")。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	void SetStateString(const FString& Key, const FString& Value);

	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	FString GetStateString(const FString& Key) const;

	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	bool IsTruthy(const FString& Key) const;

	// ── 列表(对齐 assemble.js renderRows:引擎克隆行,内容由 hook 回填)──
	/** 按 flow.list 声明克隆 Count 行并接行点击;返回实际行数。行内元素 id = "<模板id>#<行号>"。 */
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	int32 PopulateList(int32 Count);

	// ── 给 hook 用的访问器 ──
	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	UFigmaUiWidget* GetBaseWidget() const { return BaseWidget; }

	UFUNCTION(BlueprintCallable, Category = "FigmaUi")
	UFigmaUiWidget* GetModalWidget(const FString& Name) const { return ModalWidgets.FindRef(Name); }

	// ── 代理回调入口(UFigmaClickProxy 调)──
	void DispatchEvent(int32 EventIndex);
	void HandleRowClick(int32 RowIndex);

private:
	TSharedPtr<FJsonObject> LoadSpecJson(const FString& AbsPath) const;
	void ParseEvents(const TSharedPtr<FJsonObject>& Flow);
	void WireEvents();
	void SyncBindings();
	bool GuardOk(const TArray<FString>& Guards) const;
	UFigmaClickProxy* MakeProxy(int32 EventIndex, int32 RowIndex);
	void CallHookStateChanged(const FString& Key);

	UPROPERTY(Transient)
	TObjectPtr<UFigmaUiWidget> BaseWidget = nullptr;

	UPROPERTY(Transient)
	TMap<FString, TObjectPtr<UFigmaUiWidget>> ModalWidgets;

	/** 代理持有权(防 GC;UButton 委托只存弱引用语义上的绑定)。 */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UFigmaClickProxy>> Proxies;

	/** checkbox 勾号文本(懒建)。 */
	UPROPERTY(Transient)
	TObjectPtr<UTextBlock> CheckMarkText = nullptr;

	TSharedPtr<FJsonObject> FlowSpec;
	TMap<FString, TSharedPtr<FJsonValue>> State;
	TMap<FString, FString> ModalPanels; // modal 名 → panel 元素 id
	TArray<FFigmaFlowEvent> Events;

	// flow.list 声明
	FString ListModal;
	FString ListContainer;
	FString ListOnRowClick;

	// bindings.checkbox(uespec 已强类型化)
	bool bHasCheckbox = false;
	FString CheckboxEl;
	FString CheckboxFlag;
	FLinearColor CheckboxOn = FLinearColor::White;
	FLinearColor CheckboxOff = FLinearColor(1.f, 1.f, 1.f, 0.2f);
	FString CheckboxMark = TEXT("✓");
	FLinearColor CheckboxMarkColor = FLinearColor::Black;
};
