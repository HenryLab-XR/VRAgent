using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;

/// <summary>
/// Socket receiver for the pantry door lock.
/// When Key_Pantry is inserted, notifies RecipeController to advance the
/// pantry-unlock step.
/// Attach to the XRSocketInteractor on the pantry door lock socket.
/// </summary>
[RequireComponent(typeof(XRSocketInteractor))]
public class PantryKeyUnlockReceiver : MonoBehaviour
{
    [SerializeField] private DoorController pantryDoorController;
    [SerializeField] private Renderer socketIndicatorRenderer;
    [SerializeField] private Material unlockedMaterial;
    [SerializeField] private string requiredObjectName = "Key_Pantry";

    private XRSocketInteractor _socket;
    private bool _hasUnlocked = false;

    private void Awake()
    {
        _socket = GetComponent<XRSocketInteractor>();
        _socket.selectEntered.AddListener(OnItemInserted);
    }

    private void OnItemInserted(SelectEnterEventArgs args)
    {
        if (_hasUnlocked) return;
        if (pantryDoorController == null) return;

        GameObject insertedObject = args.interactableObject?.transform?.gameObject;
        if (!MatchesObjectName(insertedObject, requiredObjectName))
        {
            Debug.LogWarning($"[PantryKeyUnlockReceiver] Wrong object inserted: {(insertedObject != null ? insertedObject.name : "null")}.");
            return;
        }

        if (!pantryDoorController.TryUnlockWith(insertedObject))
        {
            Debug.LogWarning($"[PantryKeyUnlockReceiver] Wrong object inserted: {(insertedObject != null ? insertedObject.name : "null")}.");
            return;
        }

        _hasUnlocked = true;

        RecipeController.Instance?.SetPantryDoorUnlocked();

        if (socketIndicatorRenderer != null && unlockedMaterial != null)
            socketIndicatorRenderer.sharedMaterial = unlockedMaterial;

        Debug.Log("[PantryKeyUnlockReceiver] Key inserted — pantry door unlocked.");
    }

    private static bool MatchesObjectName(GameObject insertedObject, string expectedName)
    {
        if (insertedObject == null || string.IsNullOrWhiteSpace(expectedName))
            return false;

        for (Transform current = insertedObject.transform; current != null; current = current.parent)
        {
            string objectName = current.gameObject.name;
            if (objectName == expectedName || objectName == expectedName + "(Clone)")
                return true;
        }

        return false;
    }

    private void OnDestroy()
    {
        if (_socket != null)
            _socket.selectEntered.RemoveListener(OnItemInserted);
    }
}
