using UnityEngine;

/// <summary>
/// Controls door open/close animation with an optional key requirement.
/// </summary>
public class DoorController : MonoBehaviour
{
    [SerializeField] private float openAngle = 90f;
    [SerializeField] private float animationSpeed = 3f;
    public bool requiresKey = false;
    public GameObject requiredKeyObject;

    [SerializeField] private bool unlockedByKey = false;
    private bool isOpen = false;
    private Quaternion closedRotation;
    private Quaternion targetOpenRotation;

    public bool IsLocked => !CanOpen();

    private void Awake()
    {
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
        return !requiresKey || unlockedByKey;
    }

    public bool TryUnlockWith(GameObject insertedObject)
    {
        if (!requiresKey)
        {
            unlockedByKey = true;
            return true;
        }

        if (requiredKeyObject == null)
        {
            Debug.LogWarning($"[DoorController] {gameObject.name} requires a key but has no requiredKeyObject assigned.");
            return false;
        }

        if (insertedObject == null)
        {
            Debug.LogWarning($"[DoorController] {gameObject.name} received a null unlock object.");
            return false;
        }

        Transform insertedTransform = insertedObject.transform;
        Transform requiredTransform = requiredKeyObject.transform;
        if (insertedTransform == requiredTransform || insertedTransform.IsChildOf(requiredTransform))
        {
            unlockedByKey = true;
            Debug.Log($"[DoorController] {gameObject.name} unlocked by {insertedObject.name}.");
            return true;
        }

        Debug.LogWarning($"[DoorController] {gameObject.name} rejected unlock object {insertedObject.name}; required {requiredKeyObject.name}.");
        return false;
    }

    /// <summary>Opens the door if its key requirement has been satisfied.</summary>
    public void Open()
    {
        if (CanOpen()) isOpen = true;
    }

    /// <summary>Closes the door regardless of key state.</summary>
    public void Close()
    {
        isOpen = false;
    }

    /// <summary>Compatibility/debug entry point. Socket receivers should use TryUnlockWith().</summary>
    public void Unlock()
    {
        unlockedByKey = true;
        Debug.Log($"[DoorController] {gameObject.name} unlocked.");
    }
}
