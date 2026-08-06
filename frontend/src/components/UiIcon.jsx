import * as PhosphorIcons from '@phosphor-icons/react'

export default function UiIcon({
    name,
    fallbackName = 'FileText',
    weight = 'duotone',
    size = 24,
    ...props
}) {
    const Icon = PhosphorIcons[name] || PhosphorIcons[fallbackName] || PhosphorIcons.File

    if (!Icon) {
        return null
    }

    return <Icon weight={weight} size={size} color="currentColor" {...props} />
}
