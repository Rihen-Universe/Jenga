#pragma once

// =============================================================================
// NkXCBWindowImpl.h  —  Fenêtre XCB (V2)
// Create(config) sans IEventImpl — utilise NkGetEventImpl().
// =============================================================================

#include "../../Core/IWindowImpl.h"
#include <xcb/xcb.h>

namespace nkentseu
{

extern xcb_connection_t* nk_xcb_global_connection; ///< Défini dans NkXCBWindowImpl.cpp

struct NkXCBData
{
    xcb_connection_t* connection  = nullptr;
    xcb_screen_t*     screen      = nullptr;
    xcb_window_t      window      = XCB_WINDOW_NONE;
    xcb_gcontext_t    gc          = 0;
    xcb_atom_t        wmDelete    = XCB_ATOM_NONE;
    xcb_atom_t        wmProtocols = XCB_ATOM_NONE;
    xcb_cursor_t      blankCursor = 0;
    bool              isOpen      = false;
    NkU32             width       = 0;
    NkU32             height      = 0;
};

class NkXCBWindowImpl : public IWindowImpl
{
public:
    NkXCBWindowImpl()  = default;
    ~NkXCBWindowImpl() override;

    bool Create(const NkWindowConfig& config) override;
    void Close()  override;
    bool IsOpen() const override;

    std::string GetTitle()           const override;
    void        SetTitle(const std::string& t) override;
    NkVec2u     GetSize()            const override;
    NkVec2u     GetPosition()        const override;
    float       GetDpiScale()        const override { return 1.f; }
    NkVec2u     GetDisplaySize()     const override;
    NkVec2u     GetDisplayPosition() const override { return {}; }
    NkError     GetLastError()       const override;

    void SetSize(NkU32 w, NkU32 h)      override;
    void SetPosition(NkI32 x, NkI32 y)  override;
    void SetVisible(bool v)             override;
    void Minimize()                     override;
    void Maximize()                     override;
    void Restore()                      override;
    void SetFullscreen(bool fs)         override;
    void SetMousePosition(NkU32 x, NkU32 y) override;
    void ShowMouse(bool show)           override;
    void CaptureMouse(bool cap)         override;
    void SetProgress(float)             override {}

    NkSurfaceDesc GetSurfaceDesc() const override;

    xcb_window_t      GetXcbWindow()    const { return mData.window;     }
    xcb_connection_t* GetConnection()   const { return mData.connection;  }
    xcb_atom_t        GetWmDeleteAtom() const { return mData.wmDelete;    }
    xcb_atom_t        GetWmProtocolsAtom() const { return mData.wmProtocols; }

private:
    NkXCBData mData;
};

} // namespace nkentseu
