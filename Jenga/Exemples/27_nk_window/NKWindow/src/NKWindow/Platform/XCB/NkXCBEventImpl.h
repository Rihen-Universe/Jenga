#pragma once

// =============================================================================
// NkXCBEventImpl.h  —  Système d'événements XCB
//
// Table xcb_window_t → NkXCBWindowImpl*, poll XCB, keysym → NkKey.
// =============================================================================

#include "../../Core/IEventImpl.h"
#include "../../Core/Events/NkKeycodeMap.h"
#include <xcb/xcb.h>
#include <xcb/xcb_keysyms.h>
#include <unordered_map>

namespace nkentseu
{

class NkXCBWindowImpl;

class NkXCBEventImpl : public IEventImpl
{
public:
    NkXCBEventImpl();
    ~NkXCBEventImpl() override;

    // Cycle de vie
    void Initialize(IWindowImpl* owner, void* nativeHandle) override;
    void Shutdown  (void* nativeHandle)                     override;

    // Queue
    void           PollEvents()                              override;
    NkEvent*       Front()    const                          override;
    void           Pop()                                     override;
    bool           IsEmpty()  const                          override;
    void           PushEvent(std::unique_ptr<NkEvent> event) override;
    std::size_t    Size()     const                          override;

    // Callbacks
    void SetEventCallback(NkEventCallback cb)                            override;
    void SetWindowCallback(void* nativeHandle, NkEventCallback cb)       override;
    void DispatchEvent(NkEvent* event, void* nativeHandle)               override;

private:
    static NkKey           XcbKeysymToNkKey(xcb_keysym_t ks);
    static NkModifierState XcbStateMods(uint16_t state);

    struct WindowEntry
    {
        NkXCBWindowImpl* window   = nullptr;
        NkEventCallback  callback;
    };

    xcb_connection_t*  mConnection  = nullptr;
    xcb_key_symbols_t* mKeySymbols  = nullptr;
    NkEventCallback    mGlobalCallback;
    std::unordered_map<xcb_window_t, WindowEntry> mWindowMap;
};

} // namespace nkentseu
