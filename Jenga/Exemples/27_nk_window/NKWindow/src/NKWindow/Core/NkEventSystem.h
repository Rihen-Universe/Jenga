#pragma once

// =============================================================================
// NkEventSystem.h
// Système d'événements public : singleton + callbacks typés.
//
// Usage :
//   auto& es = nkentseu::EventSystem::Instance();
//   es.SetGlobalEventCallback([](nkentseu::NkEvent* ev) { ... });
//   es.SetEventCallback<nkentseu::NkWindowCloseEvent>([&](auto* ev) {
//       ev->GetWindow()->Close();
//   });
//
//   // Mode callbacks uniquement:
//   es.PollEvents();
//
//   // OU mode file d'événements utilisateur (style SFML):
//   while (auto* ev = es.PollEvent()) {
//       if (auto* kp = ev->As<nkentseu::NkKeyPressedEvent>()) { ... }
//   }
// =============================================================================

#include "NkEvent.h"
#include "NkTypedEvents.h"
#include "IEventImpl.h"
#include <functional>
#include <unordered_map>
#include <typeindex>
#include <vector>
#include <algorithm>

namespace nkentseu
{

using NkGlobalEventCallback = std::function<void(NkEvent*)>;
using NkTypedEventCallback  = std::function<void(NkEvent*)>;

// ---------------------------------------------------------------------------
// EventSystem
// ---------------------------------------------------------------------------

class EventSystem
{
public:
    // --- Singleton ---

    static EventSystem& Instance();

    EventSystem(const EventSystem&)            = delete;
    EventSystem& operator=(const EventSystem&) = delete;

    // --- Attacher / détacher des implémentations de plateforme ---

    /**
     * @brief Lie une IEventImpl concrète (appelé par Window::Create).
     *        Plusieurs implémentations peuvent être liées simultanément
     *        (plusieurs fenêtres).
     */
    void AttachImpl(IEventImpl* impl);

    /** @brief Détache une implémentation (appelé quand la fenêtre est fermée). */
    void DetachImpl(IEventImpl* impl);

    // --- Pompe d'événements ---

    /**
     * @brief Pompe les événements OS et exécute uniquement les callbacks.
     *
     * Ce mode ne fournit pas de batch lisible par PollEvent().
     * Ne pas combiner avec while(PollEvent()) dans la même trame.
     */
    void PollEvents();

    /**
     * @brief Retourne le prochain événement de la queue, ou nullptr si vide.
     *
     * Le pointeur est valide jusqu'au prochain appel de PollEvent ou PollEvents.
     * Ne pas stocker ce pointeur.
     *
     * Si la queue est vide, PollEvent() pompe automatiquement les événements
     * (callbacks + queue) en interne.
     * À utiliser seul (sans PollEvents() juste avant).
     */
    NkEvent* PollEvent();

    /**
     * @brief Variante style SFML: copie le prochain événement dans @p event.
     * @return true si un événement a été lu, sinon false.
     */
    bool PollEvent(NkEvent& event);

    // --- Callbacks global et typés ---

    /** @brief Callback reçoit TOUS les événements (avant la queue). */
    void SetGlobalEventCallback(NkGlobalEventCallback callback);

    /**
     * @brief Callback typé — déclenché uniquement pour le type T.
     *
     * @code
     *   es.SetEventCallback<NkWindowCloseEvent>([&](NkWindowCloseEvent* ev) {
     *       ev->GetWindow()->Close();
     *   });
     * @endcode
     */
    template<typename T>
    void SetEventCallback(std::function<void(T*)> callback)
    {
        mTypedCallbacks[std::type_index(typeid(T))] = [callback](NkEvent* ev)
        {
            if (auto* typed = ev->As<T>())
                callback(typed);
        };
    }

    /** @brief Supprime le callback typé pour T. */
    template<typename T>
    void RemoveEventCallback()
    {
        mTypedCallbacks.erase(std::type_index(typeid(T)));
    }

    // --- Dispatch manuel ---

    /**
     * @brief Envoie manuellement un événement dans la chaîne de callbacks.
     *        Utile pour injecter des événements synthétiques.
     */
    void DispatchEvent(NkEvent& event);

private:
    EventSystem() = default;

    void PumpEventsOnce(bool queueEvents);
    void FireTypedCallback(NkEvent* ev);

    // --- Données membres ---

    std::vector<IEventImpl*>                                      mImpls;
    NkGlobalEventCallback                                          mGlobalCallback;
    std::unordered_map<std::type_index, NkTypedEventCallback>      mTypedCallbacks;
    std::vector<NkEvent>                                           mEventBuffer;
    std::size_t                                                    mReadHead = 0;
    bool                                                           mAutoBatchActive = false;
};

} // namespace nkentseu
