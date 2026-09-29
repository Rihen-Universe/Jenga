// =============================================================================
// NkXCBEventImpl.cpp  —  Système d'événements XCB
// =============================================================================

#include "NkXCBEventImpl.h"
#include "NkXCBWindowImpl.h"
#include "../../Core/Events/NkKeycodeMap.h"
#include <X11/keysym.h>
#include <cstdlib>

namespace nkentseu
{

NkXCBEventImpl::NkXCBEventImpl()  = default;
NkXCBEventImpl::~NkXCBEventImpl()
{ if (mKeySymbols) xcb_key_symbols_free(mKeySymbols); }

// ---------------------------------------------------------------------------
// Initialize / Shutdown
// ---------------------------------------------------------------------------

void NkXCBEventImpl::Initialize(IWindowImpl* owner, void* nativeHandle)
{
    xcb_window_t wid = *static_cast<xcb_window_t*>(nativeHandle);
    auto* w = static_cast<NkXCBWindowImpl*>(owner);

    mWindowMap[wid] = { w, {} };

    // Initialise la connection XCB si ce n'est pas déjà fait
    if (!mConnection && w)
    {
        mConnection = nk_xcb_global_connection;
        if (mConnection)
            mKeySymbols = xcb_key_symbols_alloc(mConnection);
    }
}

void NkXCBEventImpl::Shutdown(void* nativeHandle)
{
    xcb_window_t wid = *static_cast<xcb_window_t*>(nativeHandle);
    mWindowMap.erase(wid);

    if (mWindowMap.empty())
    {
        if (mKeySymbols) { xcb_key_symbols_free(mKeySymbols); mKeySymbols=nullptr; }
        mConnection = nullptr;
    }
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

NkEvent*    NkXCBEventImpl::Front()   const
{ return mQueue.empty() ? nullptr : mQueue.front().get(); }
void        NkXCBEventImpl::Pop()           { if (!mQueue.empty()) mQueue.pop(); }
bool        NkXCBEventImpl::IsEmpty() const { return mQueue.empty(); }
std::size_t NkXCBEventImpl::Size()    const { return mQueue.size(); }
void        NkXCBEventImpl::PushEvent(std::unique_ptr<NkEvent> e)
{ if (e) mQueue.push(std::move(e)); }

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------

void NkXCBEventImpl::SetEventCallback(NkEventCallback cb)
{ mGlobalCallback = std::move(cb); }

void NkXCBEventImpl::SetWindowCallback(void* nativeHandle, NkEventCallback cb)
{
    xcb_window_t wid = *static_cast<xcb_window_t*>(nativeHandle);
    auto it = mWindowMap.find(wid);
    if (it != mWindowMap.end()) it->second.callback = std::move(cb);
}

void NkXCBEventImpl::DispatchEvent(NkEvent* ev, void* nativeHandle)
{
    if (nativeHandle)
    {
        xcb_window_t wid = *static_cast<xcb_window_t*>(nativeHandle);
        auto it = mWindowMap.find(wid);
        if (it != mWindowMap.end() && it->second.callback)
            it->second.callback(ev);
    }
    if (mGlobalCallback) mGlobalCallback(ev);
}

// ---------------------------------------------------------------------------
// PollEvents
// ---------------------------------------------------------------------------

void NkXCBEventImpl::PollEvents()
{
    if (!mConnection) return;

    xcb_generic_event_t* xev = nullptr;
    while ((xev = xcb_poll_for_event(mConnection)) != nullptr)
    {
        uint8_t type = xev->response_type & ~0x80;
        NkEvent nkEv;
        xcb_window_t srcWindow = 0;

        switch (type)
        {
        case XCB_KEY_PRESS:
        case XCB_KEY_RELEASE:
        {
            auto* ke = reinterpret_cast<xcb_key_press_event_t*>(xev);
            srcWindow = ke->event;

            // Position physique via evdev (keycode - 8 = USB HID)
            NkKey k = NkKeycodeMap::NkKeyFromX11Keycode(ke->detail);

            // Fallback keysym
            if (k == NkKey::NK_UNKNOWN && mKeySymbols)
            {
                xcb_keysym_t ks = xcb_key_symbols_get_keysym(mKeySymbols, ke->detail, 0);
                k = XcbKeysymToNkKey(ks);
            }

            if (k != NkKey::NK_UNKNOWN)
            {
                NkButtonState st = (type == XCB_KEY_PRESS)
                    ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED;
                NkKeyData kd;
                kd.key       = k;
                kd.state     = st;
                kd.modifiers = XcbStateMods(ke->state);
                kd.scancode  = NkScancodeFromXKeycode(ke->detail);
                kd.nativeKey = ke->detail;
                nkEv = NkEvent(kd);
            }
            break;
        }
        case XCB_BUTTON_PRESS:
        case XCB_BUTTON_RELEASE:
        {
            auto* be = reinterpret_cast<xcb_button_press_event_t*>(xev);
            srcWindow = be->event;
            NkButtonState st = (type == XCB_BUTTON_PRESS)
                ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED;
            switch (be->detail)
            {
            case 1: { NkMouseButtonData bd; bd.button=NkMouseButton::NK_MB_LEFT;   bd.state=st; bd.x=be->event_x; bd.y=be->event_y; nkEv=NkEvent(bd); } break;
            case 2: { NkMouseButtonData bd; bd.button=NkMouseButton::NK_MB_MIDDLE; bd.state=st; bd.x=be->event_x; bd.y=be->event_y; nkEv=NkEvent(bd); } break;
            case 3: { NkMouseButtonData bd; bd.button=NkMouseButton::NK_MB_RIGHT;  bd.state=st; bd.x=be->event_x; bd.y=be->event_y; nkEv=NkEvent(bd); } break;
            case 4: if (type==XCB_BUTTON_PRESS) { NkMouseWheelData wd; wd.delta=1.0; wd.deltaY=1.0; nkEv=NkEvent(NkEventType::NK_MOUSE_WHEEL_VERTICAL,wd); } break;
            case 5: if (type==XCB_BUTTON_PRESS) { NkMouseWheelData wd; wd.delta=-1.0; wd.deltaY=-1.0; nkEv=NkEvent(NkEventType::NK_MOUSE_WHEEL_VERTICAL,wd); } break;
            default: break;
            }
            break;
        }
        case XCB_MOTION_NOTIFY:
        {
            auto* me = reinterpret_cast<xcb_motion_notify_event_t*>(xev);
            srcWindow = me->event;
            NkMouseMoveData md;
            md.x=me->event_x; md.y=me->event_y;
            md.screenX=me->root_x; md.screenY=me->root_y;
            nkEv = NkEvent(md);
            break;
        }
        case XCB_CONFIGURE_NOTIFY:
        {
            auto* ce = reinterpret_cast<xcb_configure_notify_event_t*>(xev);
            srcWindow = ce->event;
            NkWindowResizeData rd;
            rd.width=ce->width; rd.height=ce->height;
            nkEv = NkEvent(rd, NkEventType::NK_WINDOW_RESIZE);
            break;
        }
        case XCB_FOCUS_IN:
        {
            auto* fe = reinterpret_cast<xcb_focus_in_event_t*>(xev);
            srcWindow = fe->event;
            nkEv = NkEvent(NkWindowFocusData(true));
            break;
        }
        case XCB_FOCUS_OUT:
        {
            auto* fe = reinterpret_cast<xcb_focus_out_event_t*>(xev);
            srcWindow = fe->event;
            nkEv = NkEvent(NkWindowFocusData(false));
            break;
        }
        case XCB_CLIENT_MESSAGE:
        {
            auto* cm = reinterpret_cast<xcb_client_message_event_t*>(xev);
            srcWindow = cm->window;
            auto it = mWindowMap.find(srcWindow);
            if (it != mWindowMap.end() && it->second.window)
            {
                if (cm->type == it->second.window->GetWmProtocolsAtom() &&
                    cm->data.data32[0] == it->second.window->GetWmDeleteAtom())
                {
                    nkEv = NkEvent(NkWindowCloseData(false));
                }
            }
            break;
        }
        default: break;
        }

        if (nkEv.IsValid())
        {
            mQueue.push(std::make_unique<NkEvent>(nkEv));
            auto it = mWindowMap.find(srcWindow);
            if (it != mWindowMap.end())
            {
                if (it->second.callback) it->second.callback(&nkEv);
            }
            if (mGlobalCallback) mGlobalCallback(&nkEv);
        }

        free(xev);
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

NkKey NkXCBEventImpl::XcbKeysymToNkKey(xcb_keysym_t ks)
{
    return NkKeycodeMap::NkKeyFromX11KeySym(static_cast<NkU32>(ks));
}

NkModifierState NkXCBEventImpl::XcbStateMods(uint16_t state)
{
    NkModifierState m;
    m.ctrl  = !!(state & XCB_MOD_MASK_CONTROL);
    m.alt   = !!(state & XCB_MOD_MASK_1);
    m.shift = !!(state & XCB_MOD_MASK_SHIFT);
    m.super = !!(state & XCB_MOD_MASK_4);
    m.capLock = !!(state & XCB_MOD_MASK_LOCK);
    m.numLock = !!(state & XCB_MOD_MASK_2);
    return m;
}

} // namespace nkentseu
