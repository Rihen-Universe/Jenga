#pragma once

// =============================================================================
// IEventImpl.h
// Interface PIMPL interne pour le système d'événements de chaque plateforme.
//
// Architecture :
//   NkSystem::Initialise() crée une instance concrète unique par plateforme.
//   Window::Create() appelle eventImpl.Initialize(this, nativeHandle).
//   Window::Close()  appelle eventImpl.Shutdown(nativeHandle).
//
// SetEventCallback / SetWindowCallback / DispatchEvent vivent ici,
// plus dans IWindowImpl.
// =============================================================================

#include "NkEvent.h"
#include <queue>
#include <memory>
#include <cstddef>
#include <functional>
#include <string>

namespace nkentseu
{

class IWindowImpl;
using NkEventCallback = std::function<void(NkEvent*)>;

// ---------------------------------------------------------------------------
// IEventImpl
// ---------------------------------------------------------------------------

class IEventImpl
{
public:
    virtual ~IEventImpl() = default;

    // -----------------------------------------------------------------------
    // Cycle de vie de la fenêtre
    // -----------------------------------------------------------------------

    /**
     * Appelé par IWindowImpl::Create() après création du handle natif.
     * Enregistre la fenêtre dans la table interne et configure les
     * périphériques d'entrée (RawInput, evdev…).
     *
     * @param owner        Fenêtre propriétaire (jamais nullptr).
     * @param nativeHandle Handle natif (HWND*, xcb_window_t*…) casté par l'impl.
     */
    virtual void Initialize(IWindowImpl* owner, void* nativeHandle) = 0;

    /**
     * Appelé par IWindowImpl::Close() avant destruction du handle.
     * Désenregistre la fenêtre.
     */
    virtual void Shutdown(void* nativeHandle) = 0;

    // -----------------------------------------------------------------------
    // Pompe d'événements
    // -----------------------------------------------------------------------

    virtual void PollEvents() = 0;

    // -----------------------------------------------------------------------
    // Queue FIFO
    //
    // La file possède ses événements (std::unique_ptr). Front() rend un
    // pointeur non possédant vers le premier, ou nullptr si la file est vide ;
    // il reste valide jusqu'au prochain Pop(). PushEvent() prend possession.
    // -----------------------------------------------------------------------

    virtual NkEvent*       Front()    const = 0;
    virtual void           Pop()            = 0;
    virtual bool           IsEmpty()  const = 0;
    virtual void           PushEvent(std::unique_ptr<NkEvent> event) = 0;
    virtual std::size_t    Size()     const = 0;

    // -----------------------------------------------------------------------
    // Callbacks événements (ont quitté IWindowImpl)
    // -----------------------------------------------------------------------

    /** Callback global : reçoit tous les événements de toutes les fenêtres. */
    virtual void SetEventCallback(NkEventCallback cb) = 0;

    /**
     * Callback par fenêtre : identifiée par son handle natif.
     * @param nativeHandle  HWND, xcb_window_t*, NSWindow*…
     */
    virtual void SetWindowCallback(void* nativeHandle, NkEventCallback cb) = 0;

    /** Dispatch un NkEvent vers le callback de la fenêtre concernée. */
    virtual void DispatchEvent(NkEvent* event, void* nativeHandle) = 0;

protected:
    std::queue<std::unique_ptr<NkEvent>> mQueue;
};

} // namespace nkentseu
