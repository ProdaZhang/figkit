// FigmaFlowComponent.cpp — flow.uespec.json → 交互流程解释器实现
// 目标引擎:UE 5.3+;依赖模块:"UMG","Slate","SlateCore","Json","JsonUtilities"
// 声明:未在引擎内编译验证 —— 交付态 = 源码 + 集成说明(references/mapping.md)。
#include "FigmaFlowComponent.h"

#include "FigmaUiWidget.h"
#include "Blueprint/UserWidget.h"
#include "Components/Button.h"
#include "Components/TextBlock.h"
#include "GameFramework/PlayerController.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogFigmaFlow, Log, All);

// 覆盖层 ZOrder 约定(根画布内;视觉元素 z 为捕获序 1..N,远小于这些):
//   9000  @panelOutside 的全帧点击层(压在视觉上、被面板盾/行按钮盖住)
//   10000+ AddClickOverlay(元素 z + 10000):面板盾、行按钮、底屏事件按钮
//   30000 @any 的全帧点击层(点哪都触发,必须最顶)
static const int32 ZOrderPanelOutside = 9000;
static const int32 ZOrderAny = 30000;

void UFigmaClickProxy::HandleClick()
{
	if (!Owner)
	{
		return;
	}
	if (RowIndex >= 0)
	{
		Owner->HandleRowClick(RowIndex);
	}
	else if (EventIndex >= 0)
	{
		Owner->DispatchEvent(EventIndex);
	}
	// 两者都 -1:面板盾,故意吞掉点击(阻止 @panelOutside 全帧层收到面板内点击)
}

// ── 装载 ─────────────────────────────────────────────────────────────────────

TSharedPtr<FJsonObject> UFigmaFlowComponent::LoadSpecJson(const FString& AbsPath) const
{
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *AbsPath))
	{
		UE_LOG(LogFigmaFlow, Error, TEXT("uespec 读取失败: %s"), *AbsPath);
		return nullptr;
	}
	TSharedPtr<FJsonObject> Obj;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Obj) || !Obj.IsValid())
	{
		UE_LOG(LogFigmaFlow, Error, TEXT("uespec 解析失败: %s"), *AbsPath);
		return nullptr;
	}
	return Obj;
}

bool UFigmaFlowComponent::InitFlow(APlayerController* OwningPlayer)
{
	if (!OwningPlayer)
	{
		UE_LOG(LogFigmaFlow, Error, TEXT("InitFlow 需要有效 PlayerController"));
		return false;
	}
	const FString Dir = FPaths::Combine(FPaths::ProjectContentDir(), SpecDirectory);
	FlowSpec = LoadSpecJson(FPaths::Combine(Dir, FlowFileName));
	if (!FlowSpec.IsValid())
	{
		return false;
	}

	// state 初值(flow.uespec 原样:bool/null/number/string)
	State.Empty();
	const TSharedPtr<FJsonObject>* St = nullptr;
	if (FlowSpec->TryGetObjectField(TEXT("state"), St))
	{
		State = (*St)->Values;
	}

	// caps:名 → uespec 文件
	const TSharedPtr<FJsonObject>* Caps = nullptr;
	FlowSpec->TryGetObjectField(TEXT("caps"), Caps);
	auto LoadCap = [&](const FString& Name) -> TSharedPtr<FJsonObject>
	{
		FString File;
		if (Caps && (*Caps)->TryGetStringField(Name, File))
		{
			return LoadSpecJson(FPaths::Combine(Dir, File));
		}
		return nullptr;
	};

	// 底屏常驻
	const FString BaseName = FlowSpec->GetStringField(TEXT("base"));
	const TSharedPtr<FJsonObject> BaseSpec = LoadCap(BaseName);
	if (!BaseSpec.IsValid())
	{
		UE_LOG(LogFigmaFlow, Error, TEXT("base cap 载入失败: %s"), *BaseName);
		return false;
	}
	BaseWidget = CreateWidget<UFigmaUiWidget>(OwningPlayer, UFigmaUiWidget::StaticClass());
	BaseWidget->BuildFromSpec(BaseSpec);
	BaseWidget->AddToViewport(0);

	// 弹窗 = 抽面板子树叠加 + 半透明遮罩(rgba(0,0,0,0.5),对齐 assemble.js),初始隐藏
	ModalWidgets.Empty();
	ModalPanels.Empty();
	const TSharedPtr<FJsonObject>* Modals = nullptr;
	int32 ModalIdx = 0;
	if (FlowSpec->TryGetObjectField(TEXT("modals"), Modals))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Modals)->Values)
		{
			const TSharedPtr<FJsonObject> M = Pair.Value->AsObject();
			if (!M.IsValid())
			{
				continue;
			}
			const TSharedPtr<FJsonObject> CapSpec = LoadCap(M->GetStringField(TEXT("cap")));
			if (!CapSpec.IsValid())
			{
				UE_LOG(LogFigmaFlow, Error, TEXT("modal %s 的 cap 载入失败"), *Pair.Key);
				continue;
			}
			TArray<FString> Roots;
			for (const TSharedPtr<FJsonValue>& R : M->GetArrayField(TEXT("roots")))
			{
				Roots.Add(R->AsString());
			}
			UFigmaUiWidget* MW = CreateWidget<UFigmaUiWidget>(OwningPlayer, UFigmaUiWidget::StaticClass());
			MW->BuildFromSpec(CapSpec, Roots, /*bDrawStageBg=*/false);
			MW->AddBackdrop(FLinearColor(0.f, 0.f, 0.f, 0.5f));
			MW->AddToViewport(50 + ModalIdx++);
			MW->SetVisibility(ESlateVisibility::Collapsed);
			ModalWidgets.Add(Pair.Key, MW);
			FString Panel;
			M->TryGetStringField(TEXT("panel"), Panel);
			ModalPanels.Add(Pair.Key, Panel);
		}
	}

	// list 声明
	ListModal.Reset();
	ListContainer.Reset();
	ListOnRowClick.Reset();
	const TSharedPtr<FJsonObject>* L = nullptr;
	if (FlowSpec->TryGetObjectField(TEXT("list"), L)) // null 时 TryGet 为 false
	{
		ListModal = (*L)->GetStringField(TEXT("modal"));
		ListContainer = (*L)->GetStringField(TEXT("container"));
		ListOnRowClick = (*L)->GetStringField(TEXT("onRowClick"));
	}

	// bindings.checkbox(颜色已由预处理器强类型化为 rgba 数组)
	bHasCheckbox = false;
	const TSharedPtr<FJsonObject>* Bindings = nullptr;
	if (FlowSpec->TryGetObjectField(TEXT("bindings"), Bindings))
	{
		const TSharedPtr<FJsonObject>* Cb = nullptr;
		if ((*Bindings)->TryGetObjectField(TEXT("checkbox"), Cb))
		{
			bHasCheckbox = true;
			CheckboxEl = (*Cb)->GetStringField(TEXT("el"));
			CheckboxFlag = (*Cb)->GetStringField(TEXT("flag"));
			CheckboxMark = (*Cb)->GetStringField(TEXT("mark"));
			const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
			if ((*Cb)->TryGetArrayField(TEXT("checkedRgba"), Arr))
			{
				CheckboxOn = UFigmaUiWidget::ColorFromRgba(Arr);
			}
			if ((*Cb)->TryGetArrayField(TEXT("uncheckedRgba"), Arr))
			{
				CheckboxOff = UFigmaUiWidget::ColorFromRgba(Arr);
			}
			if ((*Cb)->TryGetArrayField(TEXT("markRgba"), Arr))
			{
				CheckboxMarkColor = UFigmaUiWidget::ColorFromRgba(Arr);
			}
		}
	}

	ParseEvents(FlowSpec);
	WireEvents();
	SyncBindings();

	if (AppHook.GetObject())
	{
		IFigmaAppHook::Execute_OnFlowReady(AppHook.GetObject());
	}
	return true;
}

// ── 事件 ─────────────────────────────────────────────────────────────────────

void UFigmaFlowComponent::ParseEvents(const TSharedPtr<FJsonObject>& Flow)
{
	Events.Empty();
	const TArray<TSharedPtr<FJsonValue>>* Evs = nullptr;
	if (!Flow->TryGetArrayField(TEXT("events"), Evs))
	{
		return;
	}
	for (const TSharedPtr<FJsonValue>& V : *Evs)
	{
		const TSharedPtr<FJsonObject> E = V->AsObject();
		if (!E.IsValid())
		{
			continue;
		}
		FFigmaFlowEvent Ev;
		Ev.On = E->GetStringField(TEXT("on"));
		Ev.Do = E->GetStringField(TEXT("do"));
		E->TryGetStringField(TEXT("arg"), Ev.Arg); // null → 留空串
		const TArray<TSharedPtr<FJsonValue>>* Guards = nullptr;
		if (E->TryGetArrayField(TEXT("guard"), Guards))
		{
			for (const TSharedPtr<FJsonValue>& G : *Guards)
			{
				Ev.Guard.Add(G->AsString());
			}
		}
		const TArray<TSharedPtr<FJsonValue>>* Targets = nullptr;
		if (E->TryGetArrayField(TEXT("targets"), Targets))
		{
			for (const TSharedPtr<FJsonValue>& T : *Targets)
			{
				const TSharedPtr<FJsonObject> TO = T->AsObject();
				if (!TO.IsValid())
				{
					continue;
				}
				FFigmaFlowTarget Target;
				Target.Kind = TO->GetStringField(TEXT("kind"));
				TO->TryGetStringField(TEXT("id"), Target.Id);
				TO->TryGetStringField(TEXT("modal"), Target.Modal);
				Ev.Targets.Add(Target);
			}
		}
		Events.Add(Ev);
	}
}

UFigmaClickProxy* UFigmaFlowComponent::MakeProxy(int32 EventIndex, int32 RowIndex)
{
	UFigmaClickProxy* P = NewObject<UFigmaClickProxy>(this);
	P->Owner = this;
	P->EventIndex = EventIndex;
	P->RowIndex = RowIndex;
	Proxies.Add(P);
	return P;
}

void UFigmaFlowComponent::WireEvents()
{
	for (int32 i = 0; i < Events.Num(); ++i)
	{
		const FFigmaFlowEvent& Ev = Events[i];
		if (Ev.On != TEXT("click"))
		{
			UE_LOG(LogFigmaFlow, Warning, TEXT("暂只支持 click 事件,忽略 on=%s"), *Ev.On);
			continue;
		}
		for (const FFigmaFlowTarget& T : Ev.Targets)
		{
			if (T.Kind == TEXT("node"))
			{
				// 对齐 assemble.js:普通 id 只在底屏找(弹窗内交互走 @any/@panelOutside/list)
				if (UButton* Btn = BaseWidget ? BaseWidget->AddClickOverlay(T.Id) : nullptr)
				{
					Btn->OnClicked.AddDynamic(MakeProxy(i, -1), &UFigmaClickProxy::HandleClick);
				}
			}
			else if (T.Kind == TEXT("any") || T.Kind == TEXT("panelOutside"))
			{
				UFigmaUiWidget* MW = ModalWidgets.FindRef(T.Modal);
				if (!MW)
				{
					UE_LOG(LogFigmaFlow, Warning, TEXT("事件引用不存在的 modal: %s"), *T.Modal);
					continue;
				}
				const bool bAny = T.Kind == TEXT("any");
				UButton* Full = MW->AddRectOverlay(FVector2D::ZeroVector, MW->GetFrameSize(),
				                                   bAny ? ZOrderAny : ZOrderPanelOutside);
				if (Full)
				{
					Full->OnClicked.AddDynamic(MakeProxy(i, -1), &UFigmaClickProxy::HandleClick);
				}
				if (!bAny)
				{
					// 面板盾:盖住面板矩形、吞掉点击 → 只有面板外的点击落到全帧层
					const FString PanelId = ModalPanels.FindRef(T.Modal);
					if (UButton* Shield = MW->AddClickOverlay(PanelId))
					{
						Shield->OnClicked.AddDynamic(MakeProxy(-1, -1), &UFigmaClickProxy::HandleClick);
					}
				}
			}
		}
	}
}

bool UFigmaFlowComponent::GuardOk(const TArray<FString>& Guards) const
{
	for (const FString& G : Guards)
	{
		if (!IsTruthy(G))
		{
			return false;
		}
	}
	return true;
}

void UFigmaFlowComponent::DispatchEvent(int32 EventIndex)
{
	if (!Events.IsValidIndex(EventIndex))
	{
		return;
	}
	const FFigmaFlowEvent& Ev = Events[EventIndex];
	if (!GuardOk(Ev.Guard))
	{
		if (AppHook.GetObject())
		{
			IFigmaAppHook::Execute_OnGuardFail(AppHook.GetObject(), Ev.Do);
		}
		return;
	}
	if (Ev.Do == TEXT("openModal"))
	{
		OpenModal(Ev.Arg);
	}
	else if (Ev.Do == TEXT("closeModal"))
	{
		CloseModal();
	}
	else if (Ev.Do == TEXT("toggleFlag"))
	{
		ToggleFlag(Ev.Arg);
	}
	else if (Ev.Do == TEXT("send"))
	{
		if (AppHook.GetObject())
		{
			IFigmaAppHook::Execute_OnSend(AppHook.GetObject(), Ev.Arg);
		}
	}
	else if (AppHook.GetObject())
	{
		IFigmaAppHook::Execute_OnCustomAction(AppHook.GetObject(), Ev.Do, Ev.Arg);
	}
	else
	{
		UE_LOG(LogFigmaFlow, Warning, TEXT("未知 action 且无 AppHook: %s"), *Ev.Do);
	}
}

// ── 内置动作 ─────────────────────────────────────────────────────────────────

void UFigmaFlowComponent::OpenModal(const FString& Name)
{
	for (const TPair<FString, TObjectPtr<UFigmaUiWidget>>& P : ModalWidgets)
	{
		P.Value->SetVisibility(P.Key == Name ? ESlateVisibility::Visible
		                                     : ESlateVisibility::Collapsed);
	}
}

void UFigmaFlowComponent::CloseModal()
{
	for (const TPair<FString, TObjectPtr<UFigmaUiWidget>>& P : ModalWidgets)
	{
		P.Value->SetVisibility(ESlateVisibility::Collapsed);
	}
}

void UFigmaFlowComponent::ToggleFlag(const FString& Flag)
{
	const bool bNew = !IsTruthy(Flag);
	State.Add(Flag, MakeShared<FJsonValueBoolean>(bNew));
	SyncBindings();
	CallHookStateChanged(Flag);
}

void UFigmaFlowComponent::SetStateString(const FString& Key, const FString& Value)
{
	State.Add(Key, MakeShared<FJsonValueString>(Value));
	SyncBindings();
	CallHookStateChanged(Key);
}

FString UFigmaFlowComponent::GetStateString(const FString& Key) const
{
	const TSharedPtr<FJsonValue>* V = State.Find(Key);
	FString Out;
	if (V && (*V).IsValid())
	{
		(*V)->TryGetString(Out);
	}
	return Out;
}

bool UFigmaFlowComponent::IsTruthy(const FString& Key) const
{
	// 对齐 assemble.js guardOk:null/false/0/'' 为假,其余为真
	const TSharedPtr<FJsonValue>* V = State.Find(Key);
	if (!V || !(*V).IsValid() || (*V)->IsNull())
	{
		return false;
	}
	bool B = false;
	if ((*V)->TryGetBool(B))
	{
		return B;
	}
	double N = 0.0;
	if ((*V)->TryGetNumber(N))
	{
		return N != 0.0;
	}
	FString S;
	if ((*V)->TryGetString(S))
	{
		return !S.IsEmpty();
	}
	return true;
}

void UFigmaFlowComponent::CallHookStateChanged(const FString& Key)
{
	if (AppHook.GetObject())
	{
		IFigmaAppHook::Execute_OnStateChanged(AppHook.GetObject(), Key);
	}
}

// ── 绑定同步(checkbox 双态,对齐 assemble.js syncBindings)──────────────────

void UFigmaFlowComponent::SyncBindings()
{
	if (!bHasCheckbox || !BaseWidget)
	{
		return;
	}
	const bool bOn = IsTruthy(CheckboxFlag);
	BaseWidget->SetElementBrushColor(CheckboxEl, bOn ? CheckboxOn : CheckboxOff);
	if (!CheckMarkText)
	{
		// 24px 加粗勾号,对齐 assemble.js 的 fontSize:24/fontWeight:900
		CheckMarkText = BaseWidget->AddTextOverlay(CheckboxEl, FText::GetEmpty(),
		                                           CheckboxMarkColor, 24.f);
	}
	if (CheckMarkText)
	{
		CheckMarkText->SetText(bOn ? FText::FromString(CheckboxMark) : FText::GetEmpty());
	}
}

// ── 列表 ─────────────────────────────────────────────────────────────────────

int32 UFigmaFlowComponent::PopulateList(int32 Count)
{
	if (ListModal.IsEmpty() || ListContainer.IsEmpty())
	{
		UE_LOG(LogFigmaFlow, Warning, TEXT("flow 未声明 list,PopulateList 忽略"));
		return 0;
	}
	UFigmaUiWidget* MW = ModalWidgets.FindRef(ListModal);
	if (!MW)
	{
		return 0;
	}
	const int32 Made = MW->CloneListRows(ListContainer, Count);
	// 行点击:行根 id = "<模板行id>#<i>";行内容(文案/配色)由 hook 经 GetModalWidget +
	// FindByFigmaId("<子元素id>#<i>") / SetElementText 回填(域内语义不进引擎)
	for (int32 i = 0; i < Made; ++i)
	{
		// CloneListRows 用第一模板行克隆;其行根 id 前缀即容器第一子的 id。
		// 引擎无需知道具体前缀:覆盖按钮按行根 id 加 → 由 FigmaUiWidget 暴露的槽位表定位。
		// 行根 id 查询:容器第一子的原 id 在 uespec 里;这里让 FigmaUiWidget 直接按后缀找。
		const FString RowRootId = MW->FindRowRootId(ListContainer, i);
		if (RowRootId.IsEmpty())
		{
			continue;
		}
		if (UButton* Btn = MW->AddClickOverlay(RowRootId))
		{
			Btn->OnClicked.AddDynamic(MakeProxy(-1, i), &UFigmaClickProxy::HandleClick);
		}
	}
	return Made;
}

void UFigmaFlowComponent::HandleRowClick(int32 RowIndex)
{
	if (AppHook.GetObject())
	{
		IFigmaAppHook::Execute_OnListRowClicked(AppHook.GetObject(), RowIndex);
	}
	else
	{
		UE_LOG(LogFigmaFlow, Warning, TEXT("行点击 %d 无 AppHook(flow.list.onRowClick=%s)"),
		       RowIndex, *ListOnRowClick);
	}
}
