// =============================================================================
// NkXLibEventImpl.cpp  —  Système d'événements XLib
// =============================================================================

#include "NkXLibEventImpl.h"
#include "NkXLibWindowImpl.h"
#include "../../Core/Events/NkKeycodeMap.h"
#include <X11/keysym.h>
#include <utility>

namespace nkentseu
{

// ---------------------------------------------------------------------------
// Initialize / Shutdown
// ---------------------------------------------------------------------------

void NkXLibEventImpl::Initialize(IWindowImpl* owner, void* nativeHandle)
{
    ::Window wid = *static_cast<::Window*>(nativeHandle);
    auto* w = static_cast<NkXLibWindowImpl*>(owner);
    mWindowMap[wid] = { w, {} };

    if (!mDisplay && w)
        mDisplay = w->GetDisplay();
}

void NkXLibEventImpl::Shutdown(void* nativeHandle)
{
    ::Window wid = *static_cast<::Window*>(nativeHandle);
    mWindowMap.erase(wid);
    if (mWindowMap.empty())
        mDisplay = nullptr;
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

NkEvent* NkXLibEventImpl::Front() const
{ return mQueue.empty() ? nullptr : mQueue.front().get(); }
void NkXLibEventImpl::Pop()           { if (!mQueue.empty()) mQueue.pop(); }
bool NkXLibEventImpl::IsEmpty() const { return mQueue.empty(); }
std::size_t NkXLibEventImpl::Size() const { return mQueue.size(); }
void NkXLibEventImpl::PushEvent(std::unique_ptr<NkEvent> e)
{ if (e) mQueue.push(std::move(e)); }

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------

void NkXLibEventImpl::SetEventCallback(NkEventCallback cb)
{ mGlobalCallback = std::move(cb); }

void NkXLibEventImpl::SetWindowCallback(void* nativeHandle, NkEventCallback cb)
{
    ::Window wid = *static_cast<::Window*>(nativeHandle);
    auto it = mWindowMap.find(wid);
    if (it != mWindowMap.end())
        it->second.callback = std::move(cb);
}

void NkXLibEventImpl::DispatchEvent(NkEvent* ev, void* nativeHandle)
{
    if (nativeHandle)
    {
        ::Window wid = *static_cast<::Window*>(nativeHandle);
        auto it = mWindowMap.find(wid);
        if (it != mWindowMap.end() && it->second.callback)
            it->second.callback(ev);
    }
    if (mGlobalCallback)
        mGlobalCallback(ev);
}

// ---------------------------------------------------------------------------
// PollEvents
// ---------------------------------------------------------------------------

void NkXLibEventImpl::PollEvents()
{
    if (!mDisplay) return;

    while (XPending(mDisplay) > 0)
    {
        XEvent xev{};
        XNextEvent(mDisplay, &xev);

        NkEvent nkEv;
        ::Window srcWindow = xev.xany.window;

        switch (xev.type)
        {
        case KeyPress:
        case KeyRelease:
        {
            NkKey key = NkKeycodeMap::NkKeyFromX11Keycode(static_cast<NkU32>(xev.xkey.keycode));
            if (key == NkKey::NK_UNKNOWN)
            {
                KeySym ks = XLookupKeysym(&xev.xkey, 0);
                key = XlibKeysymToNkKey(ks);
            }

            if (key != NkKey::NK_UNKNOWN)
            {
                NkKeyData kd;
                kd.key       = key;
                kd.state     = (xev.type == KeyPress) ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED;
                kd.modifiers = XlibMods(xev.xkey.state);
                kd.scancode  = NkScancodeFromXKeycode(static_cast<NkU32>(xev.xkey.keycode));
                kd.nativeKey = static_cast<NkU32>(xev.xkey.keycode);
                nkEv = NkEvent(kd);
            }
            break;
        }

        case ButtonPress:
        case ButtonRelease:
        {
            NkButtonState state = (xev.type == ButtonPress) ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED;

            switch (xev.xbutton.button)
            {
            case Button1:
            {
                NkMouseButtonData bd;
                bd.button = NkMouseButton::NK_MB_LEFT;
                bd.state = state;
                bd.x = xev.xbutton.x; bd.y = xev.xbutton.y;
                bd.screenX = xev.xbutton.x_root; bd.screenY = xev.xbutton.y_root;
                bd.modifiers = XlibMods(xev.xbutton.state);
                nkEv = NkEvent(bd);
                break;
            }
            case Button2:
            {
                NkMouseButtonData bd;
                bd.button = NkMouseButton::NK_MB_MIDDLE;
                bd.state = state;
                bd.x = xev.xbutton.x; bd.y = xev.xbutton.y;
                bd.screenX = xev.xbutton.x_root; bd.screenY = xev.xbutton.y_root;
                bd.modifiers = XlibMods(xev.xbutton.state);
                nkEv = NkEvent(bd);
                break;
            }
            case Button3:
            {
                NkMouseButtonData bd;
                bd.button = NkMouseButton::NK_MB_RIGHT;
                bd.state = state;
                bd.x = xev.xbutton.x; bd.y = xev.xbutton.y;
                bd.screenX = xev.xbutton.x_root; bd.screenY = xev.xbutton.y_root;
                bd.modifiers = XlibMods(xev.xbutton.state);
                nkEv = NkEvent(bd);
                break;
            }
            case Button4:
                if (xev.type == ButtonPress)
                {
                    NkMouseWheelData wd;
                    wd.delta = 1.0;
                    wd.deltaY = 1.0;
                    wd.x = xev.xbutton.x; wd.y = xev.xbutton.y;
                    wd.modifiers = XlibMods(xev.xbutton.state);
                    nkEv = NkEvent(wd);
                }
                break;
            case Button5:
                if (xev.type == ButtonPress)
                {
                    NkMouseWheelData wd;
                    wd.delta = -1.0;
                    wd.deltaY = -1.0;
                    wd.x = xev.xbutton.x; wd.y = xev.xbutton.y;
                    wd.modifiers = XlibMods(xev.xbutton.state);
                    nkEv = NkEvent(wd);
                }
                break;
            default:
                break;
            }
            break;
        }

        case MotionNotify:
        {
            NkMouseMoveData md;
            md.x = xev.xmotion.x; md.y = xev.xmotion.y;
            md.screenX = xev.xmotion.x_root; md.screenY = xev.xmotion.y_root;
            nkEv = NkEvent(md);
            break;
        }

        case FocusIn:
            nkEv = NkEvent(NkWindowFocusData(true));
            break;
        case FocusOut:
            nkEv = NkEvent(NkWindowFocusData(false));
            break;

        case ConfigureNotify:
            nkEv = NkEvent(NkWindowResizeData(
                static_cast<NkU32>(xev.xconfigure.width),
                static_cast<NkU32>(xev.xconfigure.height)));
            break;

        case ClientMessage:
        {
            srcWindow = xev.xclient.window;
            auto it = mWindowMap.find(srcWindow);
            if (it != mWindowMap.end() && it->second.window)
            {
                XClientMessageEvent& cm = xev.xclient;
                if (cm.message_type == it->second.window->GetWmProtocolsAtom() &&
                    static_cast<Atom>(cm.data.l[0]) == it->second.window->GetWmDeleteAtom())
                {
                    nkEv = NkEvent(NkWindowCloseData(false));
                }
            }
            break;
        }

        default:
            break;
        }

        if (nkEv.IsValid())
        {
            mQueue.push(std::make_unique<NkEvent>(nkEv));
            auto it = mWindowMap.find(srcWindow);
            if (it != mWindowMap.end() && it->second.callback)
                it->second.callback(&nkEv);
            if (mGlobalCallback)
                mGlobalCallback(&nkEv);
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

NkKey NkXLibEventImpl::XlibKeysymToNkKey(KeySym ks)
{
    return NkKeycodeMap::NkKeyFromX11KeySym(static_cast<NkU32>(ks));
}

NkModifierState NkXLibEventImpl::XlibMods(unsigned int state)
{
    NkModifierState mods;
    mods.ctrl    = !!(state & ControlMask);
    mods.alt     = !!(state & Mod1Mask);
    mods.shift   = !!(state & ShiftMask);
    mods.super   = !!(state & Mod4Mask);
    mods.capLock = !!(state & LockMask);
    mods.numLock = !!(state & Mod2Mask);
    return mods;
}

} // namespace nkentseu
