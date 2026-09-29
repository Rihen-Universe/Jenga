// =============================================================================
// NkWin32EventImpl.cpp
// Pompe Win32, table HWND, WndProc, mapping VK/scancode → NkKey.
// =============================================================================

#include "NkWin32EventImpl.h"
#include "NkWin32WindowImpl.h"
#include "../../Core/Events/NkKeycodeMap.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <Windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#include <vector>
#include <algorithm>

#pragma comment(lib, "dwmapi.lib")

#ifndef HID_USAGE_PAGE_GENERIC
#define HID_USAGE_PAGE_GENERIC  ((USHORT)0x01)
#define HID_USAGE_GENERIC_MOUSE ((USHORT)0x02)
#endif

namespace nkentseu
{

// ---------------------------------------------------------------------------
// Thread-local statics
// ---------------------------------------------------------------------------

thread_local std::unordered_map<HWND, NkWin32EventImpl::WindowEntry>
    NkWin32EventImpl::sWindowMap;

thread_local NkWin32WindowImpl*
    NkWin32EventImpl::sPendingOwner     = nullptr;

thread_local NkWin32EventImpl*
    NkWin32EventImpl::sPendingEventImpl = nullptr;

// ---------------------------------------------------------------------------
// Cycle de vie
// ---------------------------------------------------------------------------

void NkWin32EventImpl::RegisterPending(NkWin32WindowImpl* owner)
{
    sPendingOwner     = owner;
    sPendingEventImpl = this;
}

void NkWin32EventImpl::Initialize(IWindowImpl* owner, void* nativeHandle)
{
    HWND hwnd = static_cast<HWND>(nativeHandle);
    WindowEntry entry;
    entry.window = static_cast<NkWin32WindowImpl*>(owner);
    sWindowMap[hwnd] = std::move(entry);

    // Enregistrement RawInput souris (une fois suffit)
    if (!mRawInputRegistered)
    {
        mRawInputRegistered = true;
        RAWINPUTDEVICE rid{};
        rid.usUsagePage = HID_USAGE_PAGE_GENERIC;
        rid.usUsage     = HID_USAGE_GENERIC_MOUSE;
        rid.dwFlags     = RIDEV_INPUTSINK;
        rid.hwndTarget  = hwnd;
        RegisterRawInputDevices(&rid, 1, sizeof(rid));
    }
}

void NkWin32EventImpl::Shutdown(void* nativeHandle)
{
    HWND hwnd = static_cast<HWND>(nativeHandle);
    sWindowMap.erase(hwnd);
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

void           NkWin32EventImpl::PollEvents()
{
    MSG msg = {};
    while (PeekMessage(&msg, nullptr, 0, 0, PM_REMOVE))
    {
        if (msg.message == WM_QUIT) break;
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
}

NkEvent*    NkWin32EventImpl::Front()   const
{ return mQueue.empty() ? nullptr : mQueue.front().get(); }

void        NkWin32EventImpl::Pop()           { if (!mQueue.empty()) mQueue.pop(); }
bool        NkWin32EventImpl::IsEmpty() const { return mQueue.empty(); }
std::size_t NkWin32EventImpl::Size()    const { return mQueue.size();  }
void        NkWin32EventImpl::PushEvent(std::unique_ptr<NkEvent> e)
{ if (e) mQueue.push(std::move(e)); }

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------

void NkWin32EventImpl::SetEventCallback(NkEventCallback cb)
{
    mGlobalCallback = std::move(cb);
}

void NkWin32EventImpl::SetWindowCallback(void* nativeHandle, NkEventCallback cb)
{
    HWND hwnd = static_cast<HWND>(nativeHandle);
    auto it   = sWindowMap.find(hwnd);
    if (it != sWindowMap.end())
        it->second.callback = std::move(cb);
}

void NkWin32EventImpl::DispatchEvent(NkEvent* event, void* nativeHandle)
{
    HWND hwnd = static_cast<HWND>(nativeHandle);

    // Callback fenêtre spécifique
    auto it = sWindowMap.find(hwnd);
    if (it != sWindowMap.end() && it->second.callback)
        it->second.callback(event);

    // Callback global
    if (mGlobalCallback)
        mGlobalCallback(event);
}

// ---------------------------------------------------------------------------
// Accès
// ---------------------------------------------------------------------------

NkWin32WindowImpl* NkWin32EventImpl::FindWindow(HWND hwnd) const
{
    auto it = sWindowMap.find(hwnd);
    return it != sWindowMap.end() ? it->second.window : nullptr;
}

// ---------------------------------------------------------------------------
// Blit software (appelé depuis NkSoftwareRendererImpl::Present)
// ---------------------------------------------------------------------------

void NkWin32EventImpl::BlitToHwnd(
    HWND hwnd, const NkU8* rgba, NkU32 w, NkU32 h)
{
    if (!hwnd || !rgba || !w || !h) return;

    // RGBA → BGRA (Win32 DIB)
    std::vector<NkU8> bgra(static_cast<std::size_t>(w) * h * 4);
    for (NkU32 i = 0; i < w * h; ++i)
    {
        bgra[i*4+0] = rgba[i*4+2];
        bgra[i*4+1] = rgba[i*4+1];
        bgra[i*4+2] = rgba[i*4+0];
        bgra[i*4+3] = rgba[i*4+3];
    }

    BITMAPINFO bmi = {};
    bmi.bmiHeader.biSize        = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth       = static_cast<LONG>(w);
    bmi.bmiHeader.biHeight      = -static_cast<LONG>(h);
    bmi.bmiHeader.biPlanes      = 1;
    bmi.bmiHeader.biBitCount    = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    HDC  hdc = GetDC(hwnd);
    RECT rc;  GetClientRect(hwnd, &rc);
    StretchDIBits(hdc,
        0, 0, rc.right - rc.left, rc.bottom - rc.top,
        0, 0, static_cast<int>(w), static_cast<int>(h),
        bgra.data(), &bmi, DIB_RGB_COLORS, SRCCOPY);
    ReleaseDC(hwnd, hdc);
}

// ---------------------------------------------------------------------------
// WndProc statique
// ---------------------------------------------------------------------------

LRESULT CALLBACK NkWin32EventImpl::WindowProcStatic(
    HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    // Phase bootstrap : WM_CREATE arrive avant que la map soit remplie
    if (msg == WM_NCCREATE || msg == WM_CREATE)
    {
        if (sPendingOwner && sPendingEventImpl)
        {
            sWindowMap[hwnd] = { sPendingOwner, {} };
            sPendingOwner     = nullptr;
            sPendingEventImpl = nullptr;
        }
    }

    auto it = sWindowMap.find(hwnd);
    if (it == sWindowMap.end())
        return DefWindowProc(hwnd, msg, wp, lp);

    NkWin32EventImpl* self  = nullptr;
    // Retrouver l'EventImpl depuis le premier sWindowMap — on cherche
    // l'instance qui contient cette HWND. Comme elle est thread_local,
    // on utilise la variable statique courante.
    // (Une seule instance d'EventImpl par thread dans ce design.)
    // Le pattern est : WindowProcStatic → ProcessWin32Message via sPendingEventImpl.
    // Mais après bootstrap, on doit localiser l'instance.
    // Solution : stocker un backpointer dans WindowEntry.
    // → On va l'ajouter dans la struct (voir ProcessWin32Message).

    // Pour l'instant, on passe par le global sPendingEventImpl
    // ou par un singleton de thread. On utilise une variable statique
    // thread_local supplémentaire qui pointe vers l'EventImpl active.
    static thread_local NkWin32EventImpl* sCurrentImpl = nullptr;

    // Au RegisterPending on sauvegarde aussi sCurrentImpl
    if (sPendingEventImpl) sCurrentImpl = sPendingEventImpl;

    if (!sCurrentImpl)
        return DefWindowProc(hwnd, msg, wp, lp);

    return sCurrentImpl->ProcessWin32Message(
        hwnd, msg, wp, lp, it->second.window);
}

// ---------------------------------------------------------------------------
// ProcessWin32Message
// ---------------------------------------------------------------------------

NkKey NkWin32EventImpl::VkeyToNkKey(WPARAM vk, LPARAM flags)
{
    bool extended = (flags >> 24) & 1;
    return NkKeycodeMap::NkKeyFromWin32VK(static_cast<NkU32>(vk), extended);
}

NkModifierState NkWin32EventImpl::CurrentMods()
{
    NkModifierState m;
    m.ctrl  = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
    m.alt   = (GetKeyState(VK_MENU)    & 0x8000) != 0;
    m.shift = (GetKeyState(VK_SHIFT)   & 0x8000) != 0;
    m.super = (GetKeyState(VK_LWIN)    & 0x8000) != 0 ||
              (GetKeyState(VK_RWIN)    & 0x8000) != 0;
    m.capLock = (GetKeyState(VK_CAPITAL) & 0x0001) != 0;
    m.numLock = (GetKeyState(VK_NUMLOCK) & 0x0001) != 0;
    return m;
}

LRESULT NkWin32EventImpl::ProcessWin32Message(
    HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
    NkWin32WindowImpl* owner)
{
    LRESULT result = 0;
    NkEvent nkEvent;
    bool suppressDefaultProc = false;

    switch (msg)
    {
    // -------------------------------------------------------------------
    // Fenêtre
    // -------------------------------------------------------------------
    case WM_CREATE:
        nkEvent = NkEvent(NkWindowCreateData(
            owner ? owner->GetConfig().width  : 0,
            owner ? owner->GetConfig().height : 0));
        break;

    case WM_CLOSE:
        nkEvent = NkEvent(NkWindowCloseData(false));
        // WM_CLOSE is a close request event. Do not force-destroy the window
        // here; the app decides by calling window.Close() or not.
        suppressDefaultProc = true;
        break;

    case WM_DESTROY:
        nkEvent = NkEvent(NkWindowDestroyData{});
        PostQuitMessage(0);
        break;

    case WM_PAINT:
    {
        PAINTSTRUCT ps;
        BeginPaint(hwnd, &ps);
        EndPaint(hwnd, &ps);
        RECT rc; GetClientRect(hwnd, &rc);
        nkEvent = NkEvent(NkWindowPaintData(
            0, 0,
            static_cast<NkU32>(rc.right - rc.left),
            static_cast<NkU32>(rc.bottom - rc.top)));
        break;
    }

    case WM_ERASEBKGND:
        result = 1;
        break;

    // -------------------------------------------------------------------
    // Focus
    // -------------------------------------------------------------------
    case WM_SETFOCUS:  nkEvent = NkEvent(NkWindowFocusData(true));  break;
    case WM_KILLFOCUS: nkEvent = NkEvent(NkWindowFocusData(false)); break;

    // -------------------------------------------------------------------
    // Souris
    // -------------------------------------------------------------------
    case WM_MOUSEMOVE:
    {
        NkI32 x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        POINT pt = {x, y};
        ClientToScreen(hwnd, &pt);
        NkMouseMoveData d;
        d.x       = x;  d.y       = y;
        d.screenX = pt.x; d.screenY = pt.y;
        d.deltaX  = x - mPrevMouseX;
        d.deltaY  = y - mPrevMouseY;
        d.modifiers = CurrentMods();
        mPrevMouseX = x; mPrevMouseY = y;
        nkEvent = NkEvent(d);
        break;
    }

    case WM_INPUT:
    {
        UINT sz = 0;
        GetRawInputData((HRAWINPUT)lp, RID_INPUT,
                        nullptr, &sz, sizeof(RAWINPUTHEADER));
        if (sz > 0)
        {
            std::vector<BYTE> buf(sz);
            if (GetRawInputData((HRAWINPUT)lp, RID_INPUT,
                                buf.data(), &sz, sizeof(RAWINPUTHEADER)) == sz)
            {
                auto* raw = reinterpret_cast<RAWINPUT*>(buf.data());
                if (raw->header.dwType == RIM_TYPEMOUSE)
                    nkEvent = NkEvent(NkMouseRawData(
                        raw->data.mouse.lLastX,
                        raw->data.mouse.lLastY, 0));
            }
        }
        break;
    }

    case WM_MOUSEWHEEL:
    {
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        ScreenToClient(hwnd, &pt);
        SHORT mk = LOWORD(wp);
        NkMouseWheelData d;
        d.delta    = GET_WHEEL_DELTA_WPARAM(wp) / (double)WHEEL_DELTA;
        d.deltaY   = d.delta;
        d.x        = static_cast<NkI32>(pt.x);
        d.y        = static_cast<NkI32>(pt.y);
        d.modifiers = NkModifierState();
        d.modifiers.ctrl  = !!(mk & MK_CONTROL);
        d.modifiers.shift = !!(mk & MK_SHIFT);
        nkEvent = NkEvent(NkEventType::NK_MOUSE_WHEEL_VERTICAL, d);
        break;
    }

    case WM_MOUSEHWHEEL:
    {
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        ScreenToClient(hwnd, &pt);
        NkMouseWheelData d;
        d.delta  = GET_WHEEL_DELTA_WPARAM(wp) / (double)WHEEL_DELTA;
        d.deltaX = d.delta;
        d.x      = static_cast<NkI32>(pt.x);
        d.y      = static_cast<NkI32>(pt.y);
        nkEvent  = NkEvent(NkEventType::NK_MOUSE_WHEEL_HORIZONTAL, d);
        break;
    }

#define NK_MB(Btn, State) { \
    POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) }; \
    POINT sp = pt; ClientToScreen(hwnd, &sp); \
    SHORT mk = LOWORD(wp); \
    NkMouseButtonData d; \
    d.button     = NkMouseButton::Btn; \
    d.state      = NkButtonState::State; \
    d.x          = pt.x; d.y = pt.y; \
    d.screenX    = sp.x; d.screenY = sp.y; \
    d.clickCount = 1; \
    d.modifiers.ctrl  = !!(mk & MK_CONTROL); \
    d.modifiers.shift = !!(mk & MK_SHIFT); \
    nkEvent = NkEvent(d); \
} break

    case WM_LBUTTONDOWN: NK_MB(NK_MB_LEFT,   NK_PRESSED);
    case WM_LBUTTONUP:   NK_MB(NK_MB_LEFT,   NK_RELEASED);
    case WM_RBUTTONDOWN: NK_MB(NK_MB_RIGHT,  NK_PRESSED);
    case WM_RBUTTONUP:   NK_MB(NK_MB_RIGHT,  NK_RELEASED);
    case WM_MBUTTONDOWN: NK_MB(NK_MB_MIDDLE, NK_PRESSED);
    case WM_MBUTTONUP:   NK_MB(NK_MB_MIDDLE, NK_RELEASED);
#undef NK_MB

    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDBLCLK:
    {
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        POINT sp = pt; ClientToScreen(hwnd, &sp);
        NkMouseButtonData d;
        d.button = (msg == WM_LBUTTONDBLCLK) ? NkMouseButton::NK_MB_LEFT
                 : (msg == WM_RBUTTONDBLCLK) ? NkMouseButton::NK_MB_RIGHT
                 : NkMouseButton::NK_MB_MIDDLE;
        d.state  = NkButtonState::NK_PRESSED;
        d.x = pt.x; d.y = pt.y;
        d.screenX = sp.x; d.screenY = sp.y;
        d.clickCount = 2;
        nkEvent = NkEvent(NkEventType::NK_MOUSE_DOUBLE_CLICK, d);
        break;
    }

    case WM_XBUTTONDOWN: case WM_XBUTTONUP:
    {
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        POINT sp = pt; ClientToScreen(hwnd, &sp);
        SHORT xb = HIWORD(wp);
        NkMouseButtonData d;
        d.button = (xb & XBUTTON1)
            ? NkMouseButton::NK_MB_BACK : NkMouseButton::NK_MB_FORWARD;
        d.state  = (msg == WM_XBUTTONDOWN)
            ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED;
        d.x = pt.x; d.y = pt.y;
        d.screenX = sp.x; d.screenY = sp.y;
        d.clickCount = 1;
        nkEvent = NkEvent(d);
        break;
    }

    case WM_MOUSELEAVE:
        nkEvent = NkEvent(NkMouseCrossData{false});
        break;

    // -------------------------------------------------------------------
    // Clavier
    // -------------------------------------------------------------------
    case WM_KEYDOWN: case WM_SYSKEYDOWN:
    case WM_KEYUP:   case WM_SYSKEYUP:
    {
        NkU32 win32Sc = (static_cast<NkU32>(lp) >> 16) & 0xFF;
        bool  isExt   = (static_cast<NkU32>(lp) >> 24) & 1;
        bool  isRep   = (static_cast<NkU32>(lp) >> 30) & 1;

        // Conversion scancode PS/2 → NkKey (position physique)
        NkKey k = NkKeycodeMap::NkKeyFromWin32Scancode(win32Sc, isExt);
        // Fallback VK
        if (k == NkKey::NK_UNKNOWN)
            k = NkKeycodeMap::NkKeyFromWin32VK(
                    static_cast<NkU32>(wp), isExt);

        if (k != NkKey::NK_UNKNOWN)
        {
            bool isPress = (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN);
            NkButtonState st = isPress
                ? (isRep ? NkButtonState::NK_REPEAT : NkButtonState::NK_PRESSED)
                : NkButtonState::NK_RELEASED;

            NkKeyData kd;
            kd.key       = k;
            kd.state     = st;
            kd.modifiers = CurrentMods();
            kd.scancode  = static_cast<NkScancode>(win32Sc);
            kd.nativeKey = static_cast<NkU32>(wp);
            kd.extended  = isExt;
            kd.repeat    = isRep;

            NkEventType et = isPress
                ? (isRep ? NkEventType::NK_KEY_REPEAT : NkEventType::NK_KEY_PRESS)
                : NkEventType::NK_KEY_RELEASE;
            nkEvent = NkEvent(et, kd);
        }
        break;
    }

    case WM_CHAR:
    {
        NkU32 cp = static_cast<NkU32>(wp);
        if (cp >= 32 && cp != 127) // Ignore control chars
        {
            NkTextInputData td = NkTextInputData::FromCodepoint(cp);
            nkEvent = NkEvent(td);
        }
        break;
    }

    // -------------------------------------------------------------------
    // Taille / Position
    // -------------------------------------------------------------------
    case WM_SIZE:
    {
        NkU32 w = LOWORD(lp), h = HIWORD(lp);
        NkWindowResizeData d;
        d.width  = w; d.height = h;
        d.prevWidth  = owner ? owner->GetConfig().width  : 0;
        d.prevHeight = owner ? owner->GetConfig().height : 0;
        nkEvent = NkEvent(d);
        break;
    }

    case WM_MOVE:
        nkEvent = NkEvent(NkWindowMoveData(
            static_cast<NkI32>(LOWORD(lp)),
            static_cast<NkI32>(HIWORD(lp))));
        break;

    case WM_SHOWWINDOW:
        nkEvent = NkEvent(NkWindowVisibilityData{wp != 0});
        break;

    // -------------------------------------------------------------------
    // DPI
    // -------------------------------------------------------------------
    case WM_DPICHANGED:
    {
        WORD dpi = HIWORD(wp);
        NkWindowDpiData d;
        d.scale     = static_cast<float>(dpi) / USER_DEFAULT_SCREEN_DPI;
        d.prevScale = owner ? owner->GetDpiScale() : 1.f;
        d.dpi       = dpi;
        nkEvent     = NkEvent(d);
        const RECT* r = reinterpret_cast<const RECT*>(lp);
        if (r)
            SetWindowPos(hwnd, nullptr,
                         r->left, r->top,
                         r->right - r->left, r->bottom - r->top,
                         SWP_NOZORDER | SWP_NOACTIVATE);
        break;
    }

    // -------------------------------------------------------------------
    // Bordure / hit-test
    // -------------------------------------------------------------------
    case WM_NCHITTEST:
        if (owner && !owner->GetConfig().frame)
        {
            RECT rc; GetWindowRect(hwnd, &rc);
            NkI32 x = GET_X_LPARAM(lp) - rc.left;
            NkI32 y = GET_Y_LPARAM(lp) - rc.top;
            NkI32 w = rc.right - rc.left, h = rc.bottom - rc.top;
            NkI32 b = IsZoomed(hwnd) ? 0 : 5;
            if (x < b && y < b)     { result = HTTOPLEFT;    break; }
            if (x > w-b && y < b)   { result = HTTOPRIGHT;   break; }
            if (x < b && y > h-b)   { result = HTBOTTOMLEFT; break; }
            if (x > w-b && y > h-b) { result = HTBOTTOMRIGHT;break; }
            if (x < b)              { result = HTLEFT;        break; }
            if (x > w-b)            { result = HTRIGHT;       break; }
            if (y < b)              { result = HTTOP;         break; }
            if (y > h-b)            { result = HTBOTTOM;      break; }
            if (y < 32 && x > 260 && x < w-260)
                                    { result = HTCAPTION;     break; }
            result = HTCLIENT;
        }
        break;

    case WM_GETMINMAXINFO:
        if (owner)
        {
            auto* mm = reinterpret_cast<MINMAXINFO*>(lp);
            mm->ptMinTrackSize.x = static_cast<LONG>(owner->GetConfig().minWidth);
            mm->ptMinTrackSize.y = static_cast<LONG>(owner->GetConfig().minHeight);
        }
        break;

    default: break;
    }

    // Dispatch : une copie part dans la file (lue par EventSystem),
    // l'original sert aux callbacks immédiats.
    if (nkEvent.IsValid())
    {
        mQueue.push(std::make_unique<NkEvent>(nkEvent));
        DispatchEvent(&nkEvent, hwnd);
    }

    if (suppressDefaultProc)
        return 0;

    return result ? result : DefWindowProc(hwnd, msg, wp, lp);
}

} // namespace nkentseu
