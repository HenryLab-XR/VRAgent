using UnityEngine;
using UnityEngine.SceneManagement;

namespace HenryLab.VRAgent.Online
{
    // =====================================================================
    //  AgentBootstrap — Auto-inject VRAgentOnline into any scene
    //
    //  Ensures that VRAgentOnline (+ AgentBridge + StateCollector) is always
    //  present in Play mode without requiring the PVEO prefab to be manually
    //  added to each scene in the editor.
    //
    //  Priority:
    //    If the scene already contains VRAgentOnline (e.g. via the PVEO
    //    prefab), nothing is done. Only creates if absent.
    //
    //  Usage:
    //    Just press Play in any scene. The TCP bridge (port 6400) is
    //    automatically available. Connect Python as usual.
    // =====================================================================

    public static class AgentBootstrap
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void EnsureOnlineAgent()
        {
#if UNITY_EDITOR
            // If already present (scene has PVEO prefab, or a previous bootstrap), skip.
            if(Object.FindAnyObjectByType<VRAgentOnline>() != null)
                return;

            // Create a persistent host object in the DontDestroyOnLoad scene.
            // DontDestroyOnLoad means it survives scene changes while still being
            // able to see all loaded regular scenes via SceneManager.
            var go = new GameObject("[VRAgentOnline-Bootstrap]");
            Object.DontDestroyOnLoad(go);

            // RequireComponent is an editor-only enforcement; add explicitly at runtime.
            go.AddComponent<AgentBridge>();
            go.AddComponent<StateCollector>();
            go.AddComponent<VRAgentOnline>();

            Debug.Log($"[AgentBootstrap] Auto-created VRAgentOnline for scene: {SceneManager.GetActiveScene().name}");
#endif
        }
    }
}
