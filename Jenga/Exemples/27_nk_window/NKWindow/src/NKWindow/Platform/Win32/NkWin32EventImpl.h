#pragma once

// =============================================================================
// NkWin32EventImpl.h
// Implémentation Win32 de IEventImpl.
//
// Responsabilités (V2 refonte) :
//   - Table HWND → (NkWin32WindowImpl*, callback) — thread_local
//   - WindowProcStatic / ProcessWin32Message — WndProc ici
//   - RegisterPending() — phase bootstrap pendant CreateWindowEx
//   - Initialize() / Shutdown() — enregistrement/désenregistrement fenêtres
//   - RawInput — enregistré à l'Initialize de la première fenêtre
//   - BlitSoftwareFramebuffer — délégué depuis IRendererImpl::Present()
//   - SetEventCallback / SetWindowCallback / DispatchEvent
// =============================================================================

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <Windows.h>
#include <windowsx.h>
#include <unordered_map>
#include <functional>
#include <vector>

#include "../../Core/IEventImpl.h"
#include "../../Core/Events/NkEventTypes.h"

namespace nkentseu
{

class NkWin32WindowImpl;

class NkWin32EventImpl : public IEventImpl
{
public:
    NkWin32EventImpl()  = default;
    ~NkWin32EventImpl() override = default;

    // -----------------------------------------------------------------------
    // IEventImpl — Cycle de vie
    // -----------------------------------------------------------------------

    void Initialize(IWindowImpl* owner, void* nativeHandle) override;
    void Shutdown  (void* nativeHandle)                     override;

    // -----------------------------------------------------------------------
    // IEventImpl — Queue
    // -----------------------------------------------------------------------

    void           PollEvents()                              override;
    NkEvent*       Front()    const                          override;
    void           Pop()                                     override;
    bool           IsEmpty()  const                          override;
    void           PushEvent(std::unique_ptr<NkEvent> event) override;
    std::size_t    Size()     const                          override;

    // -----------------------------------------------------------------------
    // IEventImpl — Callbacks
    // -----------------------------------------------------------------------

    void SetEventCallback  (NkEventCallback cb)                      override;
    void SetWindowCallback (void* nativeHandle, NkEventCallback cb)  override;
    void DispatchEvent     (NkEvent* event, void* nativeHandle)      override;

    // -----------------------------------------------------------------------
    // Bootstrap CreateWindowEx (appelé par NkWin32WindowImpl::Create)
    // -----------------------------------------------------------------------

    /**
     * Enregistre la fenêtre en attente AVANT CreateWindowEx.
     * Pendant WM_CREATE, WindowProcStatic l'insère dans la table.
     */
    void RegisterPending(NkWin32WindowImpl* owner);

    // -----------------------------------------------------------------------
    // WndProc statique — publique pour que NkWin32WindowImpl puisse la passer
    // à RegisterClassEx.
    // -----------------------------------------------------------------------

    static LRESULT CALLBACK WindowProcStatic(
        HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

    // -----------------------------------------------------------------------
    // Blit software (appelé depuis NkSoftwareRendererImpl::Present)
    // -----------------------------------------------------------------------

    static void BlitToHwnd(HWND hwnd,
                            const NkU8* rgbaPixels, NkU32 w, NkU32 h);

    // -----------------------------------------------------------------------
    // Accès
    // -----------------------------------------------------------------------

    NkWin32WindowImpl* FindWindow(HWND hwnd) const;

private:
    LRESULT ProcessWin32Message(
        HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
        NkWin32WindowImpl* owner);

    static NkKey           VkeyToNkKey(WPARAM vk, LPARAM flags);
    static NkModifierState CurrentMods();

    // -----------------------------------------------------------------------
    // Table thread_local : HWND → entrée (WindowImpl + callback)
    // -----------------------------------------------------------------------

    struct WindowEntry
    {
        NkWin32WindowImpl* window   = nullptr;
        NkEventCallback    callback;
    };

    // Thread_local car les fenêtres Win32 appartiennent au thread créateur.
    static thread_local std::unordered_map<HWND, WindowEntry> sWindowMap;

    // Bootstrap : pendant CreateWindowEx le HWND n'est pas encore dans la map.
    static thread_local NkWin32WindowImpl* sPendingOwner;
    static thread_local NkWin32EventImpl*  sPendingEventImpl;

    NkEventCallback  mGlobalCallback;
    bool             mRawInputRegistered = false;
    NkI32            mPrevMouseX = 0;
    NkI32            mPrevMouseY = 0;
};

} // namespace nkentseu
