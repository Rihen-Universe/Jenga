// =============================================================================
// NkCocoaEventImpl.mm
// Pompe d'evenements NSApp pour macOS.
// =============================================================================

#import <Cocoa/Cocoa.h>

#include "NkCocoaEventImpl.h"
#include "NkCocoaWindowImpl.h"
#include "../../Core/Events/NkKeycodeMap.h"
#include "../../Core/Events/NkScancode.h"

#include <utility>

namespace nkentseu
{

// ---------------------------------------------------------------------------
// Initialize / Shutdown
// ---------------------------------------------------------------------------

void NkCocoaEventImpl::Initialize(IWindowImpl* owner, void* nativeHandle)
{
    auto* window = static_cast<NkCocoaWindowImpl*>(owner);

    if (!nativeHandle && window)
        nativeHandle = reinterpret_cast<void*>(window->GetNSWindow());

    if (!nativeHandle)
        return;

    mWindowMap[nativeHandle] = { window, {} };
}

void NkCocoaEventImpl::Shutdown(void* nativeHandle)
{
    if (nativeHandle)
    {
        mWindowMap.erase(nativeHandle);
        return;
    }

    if (!mWindowMap.empty())
        mWindowMap.erase(mWindowMap.begin());
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

NkEvent* NkCocoaEventImpl::Front() const
{ return mQueue.empty() ? nullptr : mQueue.front().get(); }

void NkCocoaEventImpl::Pop() { if (!mQueue.empty()) mQueue.pop(); }
bool NkCocoaEventImpl::IsEmpty() const { return mQueue.empty(); }
std::size_t NkCocoaEventImpl::Size() const { return mQueue.size(); }
void NkCocoaEventImpl::PushEvent(std::unique_ptr<NkEvent> e)
{ if (e) mQueue.push(std::move(e)); }

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------

void NkCocoaEventImpl::SetEventCallback(NkEventCallback cb)
{
    mGlobalCallback = std::move(cb);
}

void NkCocoaEventImpl::SetWindowCallback(void* nativeHandle, NkEventCallback cb)
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

void NkCocoaEventImpl::DispatchEvent(NkEvent* event, void* nativeHandle)
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

// ---------------------------------------------------------------------------
// PollEvents
// ---------------------------------------------------------------------------

void NkCocoaEventImpl::PollEvents()
{
    @autoreleasepool
    {
        NSEvent* ev = nil;
        while ((ev = [NSApp nextEventMatchingMask:NSEventMaskAny
                                       untilDate:[NSDate distantPast]
                                          inMode:NSDefaultRunLoopMode
                                         dequeue:YES]) != nil)
        {
            [NSApp sendEvent:ev];

            NkEvent nkEv;
            void* nativeHandle = (__bridge void*)[ev window];
            if (!nativeHandle && !mWindowMap.empty())
                nativeHandle = mWindowMap.begin()->first;

            switch ([ev type])
            {
            case NSEventTypeKeyDown:
            case NSEventTypeKeyUp:
            {
                const unsigned short macKC = [ev keyCode];
                const NkScancode sc = NkScancodeFromMac(macKC);

                NkKey key = NkScancodeToKey(sc);
                if (key == NkKey::NK_UNKNOWN)
                    key = MacKeycodeToNkKey(macKC);

                if (key != NkKey::NK_UNKNOWN)
                {
                    const bool isRepeat = ([ev type] == NSEventTypeKeyDown) && ([ev isARepeat] == YES);
                    const NkButtonState st = ([ev type] == NSEventTypeKeyUp)
                        ? NkButtonState::NK_RELEASED
                        : (isRepeat ? NkButtonState::NK_REPEAT : NkButtonState::NK_PRESSED);

                    NkKeyData kd(key,
                                 st,
                                 NsModsToMods([ev modifierFlags]),
                                 sc,
                                 static_cast<NkU32>(macKC),
                                 false,
                                 isRepeat);
                    nkEv = NkEvent(kd);
                }
                break;
            }

            case NSEventTypeMouseMoved:
            case NSEventTypeLeftMouseDragged:
            case NSEventTypeRightMouseDragged:
            case NSEventTypeOtherMouseDragged:
            {
                const NSPoint p = [ev locationInWindow];
                const NSPoint screenP = [NSEvent mouseLocation];

                NkU32 buttonsDown = 0;
                const NSUInteger pressedButtons = [NSEvent pressedMouseButtons];
                if (pressedButtons & (1u << 0)) buttonsDown |= (1u << static_cast<NkU32>(NkMouseButton::NK_MB_LEFT));
                if (pressedButtons & (1u << 1)) buttonsDown |= (1u << static_cast<NkU32>(NkMouseButton::NK_MB_RIGHT));
                if (pressedButtons & (1u << 2)) buttonsDown |= (1u << static_cast<NkU32>(NkMouseButton::NK_MB_MIDDLE));
                if (pressedButtons & (1u << 3)) buttonsDown |= (1u << static_cast<NkU32>(NkMouseButton::NK_MB_BACK));
                if (pressedButtons & (1u << 4)) buttonsDown |= (1u << static_cast<NkU32>(NkMouseButton::NK_MB_FORWARD));

                NkMouseMoveData md(
                    static_cast<NkI32>(p.x),
                    static_cast<NkI32>(p.y),
                    static_cast<NkI32>(screenP.x),
                    static_cast<NkI32>(screenP.y),
                    static_cast<NkI32>([ev deltaX]),
                    static_cast<NkI32>([ev deltaY]),
                    buttonsDown,
                    NsModsToMods([ev modifierFlags]));

                nkEv = NkEvent(md);
                break;
            }

            case NSEventTypeLeftMouseDown:
            case NSEventTypeLeftMouseUp:
            case NSEventTypeRightMouseDown:
            case NSEventTypeRightMouseUp:
            case NSEventTypeOtherMouseDown:
            case NSEventTypeOtherMouseUp:
            {
                NkMouseButton button = NkMouseButton::NK_MB_UNKNOWN;

                if ([ev type] == NSEventTypeLeftMouseDown || [ev type] == NSEventTypeLeftMouseUp)
                {
                    button = NkMouseButton::NK_MB_LEFT;
                }
                else if ([ev type] == NSEventTypeRightMouseDown || [ev type] == NSEventTypeRightMouseUp)
                {
                    button = NkMouseButton::NK_MB_RIGHT;
                }
                else
                {
                    const NSInteger n = [ev buttonNumber];
                    if (n == 2)      button = NkMouseButton::NK_MB_MIDDLE;
                    else if (n == 3) button = NkMouseButton::NK_MB_BACK;
                    else if (n == 4) button = NkMouseButton::NK_MB_FORWARD;
                }

                if (button != NkMouseButton::NK_MB_UNKNOWN)
                {
                    const bool isDown = ([ev type] == NSEventTypeLeftMouseDown)
                                     || ([ev type] == NSEventTypeRightMouseDown)
                                     || ([ev type] == NSEventTypeOtherMouseDown);

                    const NSPoint p = [ev locationInWindow];
                    const NSPoint screenP = [NSEvent mouseLocation];

                    NkMouseButtonData bd(
                        button,
                        isDown ? NkButtonState::NK_PRESSED : NkButtonState::NK_RELEASED,
                        static_cast<NkI32>(p.x),
                        static_cast<NkI32>(p.y),
                        static_cast<NkI32>(screenP.x),
                        static_cast<NkI32>(screenP.y),
                        NsModsToMods([ev modifierFlags]),
                        static_cast<NkU32>([ev clickCount]));

                    nkEv = NkEvent(bd);
                }
                break;
            }

            case NSEventTypeScrollWheel:
            {
                const NSPoint p = [ev locationInWindow];

                NkMouseWheelData wd;
                wd.delta = [ev scrollingDeltaY];
                wd.deltaX = [ev scrollingDeltaX];
                wd.deltaY = [ev scrollingDeltaY];
                wd.x = static_cast<NkI32>(p.x);
                wd.y = static_cast<NkI32>(p.y);
                wd.modifiers = NsModsToMods([ev modifierFlags]);
                wd.highPrecision = ([ev hasPreciseScrollingDeltas] == YES);
                if (wd.highPrecision)
                {
                    wd.pixelDeltaX = wd.deltaX;
                    wd.pixelDeltaY = wd.deltaY;
                }

                nkEv = NkEvent(wd);
                break;
            }

            default:
                break;
            }

            if (nkEv.IsValid())
            {
                mQueue.push(std::make_unique<NkEvent>(nkEv));
                DispatchEvent(&nkEv, nativeHandle);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

NkKey NkCocoaEventImpl::MacKeycodeToNkKey(unsigned short code)
{
    return NkKeycodeMap::NkKeyFromMacKeyCode(static_cast<NkU16>(code));
}

NkModifierState NkCocoaEventImpl::NsModsToMods(unsigned long flags)
{
    NkModifierState mods;
    mods.ctrl    = !!(flags & NSEventModifierFlagControl);
    mods.alt     = !!(flags & NSEventModifierFlagOption);
    mods.shift   = !!(flags & NSEventModifierFlagShift);
    mods.super   = !!(flags & NSEventModifierFlagCommand);
    mods.capLock = !!(flags & NSEventModifierFlagCapsLock);
    return mods;
}

} // namespace nkentseu
