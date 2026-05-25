using UnityEngine;

/// <summary>
/// Controls door open/close animation with optional locked state.
/// Unlock() or TryUnlockWith() must be called before Open() has any effect.
/// </summary>
public class DoorController : MonoBehaviour
{
    [SerializeField] private float openAngle = 90f;
    [SerializeField] private float animationSpeed = 3f;
    [SerializeField] private bool startLocked = true;
    [SerializeField] private bool requiresKey = false;
    [SerializeField] private GameObject requiredKeyObject;

    private bool isLocked;
    private bool isOpen = false;
    private Quaternion closedRotation;
    private Quaternion targetOpenRotation;

    public bool IsLocked => isLocked;

    private void Awake()
    {
        isLocked = startLocked;
        // Initialize rotation targets before runtime triggers can call Open().
        closedRotation = transform.localRotation;
        targetOpenRotation = Quaternion.Euler(0f, openAngle, 0f) * closedRotation;
    }

    private void Update()
    {
        Quaternion target = isOpen ? targetOpenRotation : closedRotation;
        transform.localRotation = Quaternion.Lerp(transform.localRotation, target, Time.deltaTime * animationSpeed);
    }

    public bool CanOpen()
    {
        return !isLocked;
    }

    public bool TryUnlockWith(GameObject insertedObject)
    {
        if (!gameObject.scene.isLoaded)
        {
            bool unlocked = false;
            foreach (DoorController doorController in FindObjectsOfType<DoorController>())
                unlocked |= doorController.TryUnlockWith(insertedObject);
            return unlocked;
        }

        if (insertedObject == null)
        {
            Debug.LogWarning($"[DoorController] {gameObject.name} received a null unlock object.");
            return false;
        }

        if (requiresKey && requiredKeyObject == null)
        {
            Debug.LogWarning($"[DoorController] {gameObject.name} requires a key but has no requiredKeyObject assigned.");
            return false;
        }

        if (requiredKeyObject != null && !MatchesRequiredObject(insertedObject, requiredKeyObject))
        {
            Debug.LogWarning($"[DoorController] {gameObject.name} rejected unlock object {insertedObject.name}; required {requiredKeyObject.name}.");
            return false;
        }

        Unlock();
        return true;
    }

    private static bool MatchesRequiredObject(GameObject insertedObject, GameObject requiredObject)
    {
        Transform inserted = insertedObject.transform;
        Transform required = requiredObject.transform;
        return inserted == required || inserted.IsChildOf(required);
    }

    /// <summary>Opens the door. No effect if locked.</summary>
    public void Open()
    {
        if (CanOpen())
            isOpen = true;
    }

    /// <summary>Closes the door regardless of lock state.</summary>
    public void Close()
    {
        isOpen = false;
    }

    /// <summary>Removes the lock so the door can be opened.</summary>
    public void Unlock()
    {

        isLocked = false;
        Debug.Log($"[DoorController] {gameObject.name} unlocked.");
    }
}
