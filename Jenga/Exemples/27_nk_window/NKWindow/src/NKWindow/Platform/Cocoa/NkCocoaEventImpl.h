#pragma once

// =============================================================================
// NkCocoaEventImpl.h  —  Système d'événements Cocoa (macOS)
// Table NSWindow* → NkCocoaWindowImpl*, poll NSApplication, keycodes → NkKey.
// =============================================================================

#include "../../Core/IEventImpl.h"
#include <unordered_map>

namespace nkentseu
{
class NkCocoaWindowImpl;

class NkCocoaEventImpl : public IEventImpl
{
public:
    NkCocoaEventImpl()  = default;
    ~NkCocoaEventImpl() override = default;

    void Initialize(IWindowImpl* owner, void* nativeHandle) override;
    void Shutdown  (void* nativeHandle)                     override;

    void           PollEvents()                              override;
    NkEvent*       Front()    const                          override;
    void           Pop()                                     override;
    bool           IsEmpty()  const                          override;
    void           PushEvent(std::unique_ptr<NkEvent> event) override;
    std::size_t    Size()     const                          override;

    void SetEventCallback(NkEventCallback cb)                            override;
    void SetWindowCallback(void* nativeHandle, NkEventCallback cb)       override;
    void DispatchEvent(NkEvent* event, void* nativeHandle)               override;

private:
    static NkKey           MacKeycodeToNkKey(unsigned short code);
    static NkModifierState NsModsToMods(unsigned long flags);

    struct WindowEntry { NkCocoaWindowImpl* window = nullptr; NkEventCallback callback; };
    // nativeHandle = NSWindow* (pointeur opaque)
    NkEventCallback mGlobalCallback;
    std::unordered_map<void*, WindowEntry> mWindowMap;
};
} // namespace nkentseu
