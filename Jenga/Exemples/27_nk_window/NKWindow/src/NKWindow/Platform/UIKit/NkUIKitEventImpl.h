#pragma once
// NkUIKitEventImpl.h — stub UIKit/iOS
#include "../../Core/IEventImpl.h"
namespace nkentseu {
class NkUIKitEventImpl : public IEventImpl {
public:
    void Initialize(IWindowImpl*,void*) override {}
    void Shutdown(void*)                override {}
    void PollEvents()                   override {}
    NkEvent* Front() const override { return nullptr; }
    void Pop()             override {}
    bool IsEmpty() const   override { return true; }
    void PushEvent(std::unique_ptr<NkEvent>) override {}
    std::size_t Size() const override { return 0; }
    void SetEventCallback(NkEventCallback)         override {}
    void SetWindowCallback(void*,NkEventCallback)  override {}
    void DispatchEvent(NkEvent*,void*)             override {}
};
}
