// =============================================================================
// NkAndroidEventImpl.cpp
// =============================================================================

#include "NkAndroidEventImpl.h"
#include "NkAndroidWindowImpl.h"
#include <android/looper.h>
#include <utility>

namespace nkentseu
{

NkAndroidEventImpl* NkAndroidEventImpl::sInstance = nullptr;

void NkAndroidEventImpl::Initialize(IWindowImpl* owner, void* nativeHandle)
{
    auto* window = static_cast<NkAndroidWindowImpl*>(owner);
    if (nativeHandle)
        mWindowMap[nativeHandle] = { window, {} };

    if (!mApp)
        mApp = nk_android_global_app;

    if (mApp)
    {
        sInstance = this;
        mApp->onAppCmd = OnAppCmd;
        mApp->onInputEvent = OnInputEvent;
    }
}

void NkAndroidEventImpl::Shutdown(void* nativeHandle)
{
    if (nativeHandle)
        mWindowMap.erase(nativeHandle);

    if (!mWindowMap.empty())
        return;

    if (mApp && sInstance == this)
    {
        mApp->onAppCmd = nullptr;
        mApp->onInputEvent = nullptr;
    }
    mApp = nullptr;

    if (sInstance == this)
        sInstance = nullptr;
}

NkEvent*    NkAndroidEventImpl::Front()   const
{ return mQueue.empty() ? nullptr : mQueue.front().get(); }
void        NkAndroidEventImpl::Pop()           { if (!mQueue.empty()) mQueue.pop(); }
bool        NkAndroidEventImpl::IsEmpty() const { return mQueue.empty(); }
std::size_t NkAndroidEventImpl::Size()    const { return mQueue.size(); }
void        NkAndroidEventImpl::PushEvent(std::unique_ptr<NkEvent> e)
{ if (e) mQueue.push(std::move(e)); }

void NkAndroidEventImpl::PollEvents()
{
    if (!mApp) return;
    int events;
    struct android_poll_source* source;
    // Use ALooper_pollOnce instead of deprecated ALooper_pollAll
    while (ALooper_pollOnce(0, nullptr, &events, (void**)&source) >= 0)
        if (source) source->process(mApp, source);
}

void NkAndroidEventImpl::SetEventCallback(NkEventCallback cb)
{
    mGlobalCallback = std::move(cb);
}

void NkAndroidEventImpl::SetWindowCallback(void* nativeHandle, NkEventCallback cb)
{
    if (!nativeHandle)
    {
        for (auto it = mWindowMap.begin(); it != mWindowMap.end(); ++it)
            it->second.callback = cb;
        return;
    }

    auto it = mWindowMap.find(nativeHandle);
    if (it != mWindowMap.end())
        it->second.callback = std::move(cb);
}

void NkAndroidEventImpl::DispatchEvent(NkEvent* event, void* nativeHandle)
{
    if (nativeHandle)
    {
        auto it = mWindowMap.find(nativeHandle);
        if (it != mWindowMap.end() && it->second.callback)
            it->second.callback(event);
    }
    else
    {
        for (auto it = mWindowMap.begin(); it != mWindowMap.end(); ++it)
        {
            if (it->second.callback)
                it->second.callback(event);
        }
    }

    if (mGlobalCallback)
        mGlobalCallback(event);
}

void NkAndroidEventImpl::OnAppCmd(android_app* app, int32_t cmd)
{
    if (!sInstance) return;
    NkEvent ev;
    switch (cmd)
    {
    case APP_CMD_INIT_WINDOW:   ev = NkEvent(NkEventType::NK_WINDOW_CREATE);  break;
    case APP_CMD_TERM_WINDOW:   ev = NkEvent(NkEventType::NK_WINDOW_DESTROY); break;
    case APP_CMD_GAINED_FOCUS:  ev = NkEvent(NkFocusData(true));       break;
    case APP_CMD_LOST_FOCUS:    ev = NkEvent(NkFocusData(false));      break;
    case APP_CMD_WINDOW_RESIZED:
    {
        ANativeWindow* w = app->window;
        if (w)
            ev = NkEvent(NkResizeData(
                static_cast<NkU32>(ANativeWindow_getWidth(w)),
                static_cast<NkU32>(ANativeWindow_getHeight(w)), false));
        break;
    }
    default: return;
    }
    if (ev.IsValid())
    {
        sInstance->mQueue.push(std::make_unique<NkEvent>(ev));
        void* nativeHandle = app ? static_cast<void*>(app->window) : nullptr;
        if (!nativeHandle && !sInstance->mWindowMap.empty())
            nativeHandle = sInstance->mWindowMap.begin()->first;
        sInstance->DispatchEvent(&ev, nativeHandle);
    }
}

int32_t NkAndroidEventImpl::OnInputEvent(android_app* app, AInputEvent* aev)
{
    if (!sInstance) return 0;
    NkEvent ev;
    if (AInputEvent_getType(aev) == AINPUT_EVENT_TYPE_MOTION)
    {
        NkI32 x = static_cast<NkI32>(AMotionEvent_getX(aev, 0));
        NkI32 y = static_cast<NkI32>(AMotionEvent_getY(aev, 0));
        int32_t act = AMotionEvent_getAction(aev) & AMOTION_EVENT_ACTION_MASK;
        if (act == AMOTION_EVENT_ACTION_DOWN)
            ev = NkEvent(NkMouseInputData(NkMouseButton::NK_MB_LEFT, NkButtonState::NK_PRESSED, x, y));
        else if (act == AMOTION_EVENT_ACTION_UP)
            ev = NkEvent(NkMouseInputData(NkMouseButton::NK_MB_LEFT, NkButtonState::NK_RELEASED, x, y));
        else if (act == AMOTION_EVENT_ACTION_MOVE)
            ev = NkEvent(NkMouseMoveData(x, y, x, y, 0, 0));
    }
    else if (AInputEvent_getType(aev) == AINPUT_EVENT_TYPE_KEY)
    {
        int32_t kc = AKeyEvent_getKeyCode(aev);
        NkKey k = AkeyToNkKey(kc);
        if (k != NkKey::NK_KEY_MAX)
        {
            int32_t act = AKeyEvent_getAction(aev);
            NkButtonState st = (act == AKEY_EVENT_ACTION_DOWN)
                ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED;
            ev = NkEvent(NkKeyboardData(k, st, {}));
        }
    }
    if (ev.IsValid())
    {
        sInstance->mQueue.push(std::make_unique<NkEvent>(ev));
        void* nativeHandle = app ? static_cast<void*>(app->window) : nullptr;
        if (!nativeHandle && !sInstance->mWindowMap.empty())
            nativeHandle = sInstance->mWindowMap.begin()->first;
        sInstance->DispatchEvent(&ev, nativeHandle);
        return 1;
    }
    return 0;
}

NkKey NkAndroidEventImpl::AkeyToNkKey(int32_t kc)
{
    switch (kc)
    {
    case AKEYCODE_ESCAPE:     return NkKey::NK_ESCAPE;
    case AKEYCODE_A:          return NkKey::NK_A;
    case AKEYCODE_B:          return NkKey::NK_B;
    case AKEYCODE_C:          return NkKey::NK_C;
    case AKEYCODE_D:          return NkKey::NK_D;
    case AKEYCODE_E:          return NkKey::NK_E;
    case AKEYCODE_F:          return NkKey::NK_F;
    case AKEYCODE_G:          return NkKey::NK_G;
    case AKEYCODE_H:          return NkKey::NK_H;
    case AKEYCODE_I:          return NkKey::NK_I;
    case AKEYCODE_J:          return NkKey::NK_J;
    case AKEYCODE_K:          return NkKey::NK_K;
    case AKEYCODE_L:          return NkKey::NK_L;
    case AKEYCODE_M:          return NkKey::NK_M;
    case AKEYCODE_N:          return NkKey::NK_N;
    case AKEYCODE_O:          return NkKey::NK_O;
    case AKEYCODE_P:          return NkKey::NK_P;
    case AKEYCODE_Q:          return NkKey::NK_Q;
    case AKEYCODE_R:          return NkKey::NK_R;
    case AKEYCODE_S:          return NkKey::NK_S;
    case AKEYCODE_T:          return NkKey::NK_T;
    case AKEYCODE_U:          return NkKey::NK_U;
    case AKEYCODE_V:          return NkKey::NK_V;
    case AKEYCODE_W:          return NkKey::NK_W;
    case AKEYCODE_X:          return NkKey::NK_X;
    case AKEYCODE_Y:          return NkKey::NK_Y;
    case AKEYCODE_Z:          return NkKey::NK_Z;
    case AKEYCODE_0:          return NkKey::NK_NUM0;
    case AKEYCODE_1:          return NkKey::NK_NUM1;
    case AKEYCODE_2:          return NkKey::NK_NUM2;
    case AKEYCODE_3:          return NkKey::NK_NUM3;
    case AKEYCODE_4:          return NkKey::NK_NUM4;
    case AKEYCODE_5:          return NkKey::NK_NUM5;
    case AKEYCODE_6:          return NkKey::NK_NUM6;
    case AKEYCODE_7:          return NkKey::NK_NUM7;
    case AKEYCODE_8:          return NkKey::NK_NUM8;
    case AKEYCODE_9:          return NkKey::NK_NUM9;
    case AKEYCODE_SPACE:      return NkKey::NK_SPACE;
    case AKEYCODE_ENTER:      return NkKey::NK_ENTER;
    case AKEYCODE_DEL:        return NkKey::NK_BACK;
    case AKEYCODE_TAB:        return NkKey::NK_TAB;
    case AKEYCODE_SHIFT_LEFT: return NkKey::NK_LSHIFT;
    case AKEYCODE_SHIFT_RIGHT:return NkKey::NK_RSHIFT;
    case AKEYCODE_CTRL_LEFT:  return NkKey::NK_LCTRL;
    case AKEYCODE_CTRL_RIGHT: return NkKey::NK_RCTRL;
    case AKEYCODE_ALT_LEFT:   return NkKey::NK_LALT;
    case AKEYCODE_ALT_RIGHT:  return NkKey::NK_RALT;
    case AKEYCODE_DPAD_UP:    return NkKey::NK_UP;
    case AKEYCODE_DPAD_DOWN:  return NkKey::NK_DOWN;
    case AKEYCODE_DPAD_LEFT:  return NkKey::NK_LEFT;
    case AKEYCODE_DPAD_RIGHT: return NkKey::NK_RIGHT;
    default:                  return NkKey::NK_KEY_MAX;
    }
}

} // namespace nkentseu
