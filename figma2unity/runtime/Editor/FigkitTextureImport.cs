using UnityEditor;
using UnityEngine;

namespace Figkit.EditorTools
{
    /// <summary>
    /// 把 figkit 导出的 UI 图按 **UI 的规矩**导入,而不是 Unity 的默认值。
    ///
    /// 默认值是给 3D 贴图定的,对 UI 是三重灾难 —— 这三条是拿实机像素比出来的
    /// (2026-08-05,已领取那屏的白色对勾):
    ///   ① `mipmapEnabled = true`:UI 是 1:1 贴的,却可能采到更低一级 mip,
    ///      边缘因此**向外扩散** —— 白勾比 HTML 每边胖 1px、底部那行被硬切平,
    ///      同一格里的金色小星反而**向内缩** 1px(亮的外扩、暗的内缩,是同一件事)。
    ///   ② `textureCompression = Normal`(DXT/BC 块压缩):高对比边缘出块状伪影,颜色也偏。
    ///   ③ `alphaIsTransparency = false`:全透明像素的 RGB 不做扩散,
    ///      半透明边缘会渗出黑边。
    /// 另外把 wrapMode 钉成 Clamp:UI 图不平铺,Repeat 会让边缘采到对侧像素。
    ///
    /// 只作用于 <see cref="Root"/> 下的资源,不碰集成方自己的贴图。
    /// 换目录就改这个常量;要整批生效,改完在 Project 里对该目录 Reimport 一次。
    /// </summary>
    public class FigkitTextureImport : AssetPostprocessor
    {
        /// figkit 图片的落地目录(与 assets-manifest.json 的约定一致)。
        public const string Root = "Assets/Resources/UI/";

        void OnPreprocessTexture()
        {
            if (!assetPath.StartsWith(Root)) return;
            var im = (TextureImporter)assetImporter;
            im.textureType = TextureImporterType.Default;
            im.mipmapEnabled = false;              // ①
            im.alphaIsTransparency = true;         // ③
            im.wrapMode = TextureWrapMode.Clamp;
            im.filterMode = FilterMode.Bilinear;
            im.npotScale = TextureImporterNPOTScale.None;
            im.sRGBTexture = true;
            var s = im.GetDefaultPlatformTextureSettings();
            s.textureCompression = TextureImporterCompression.Uncompressed;   // ②
            s.crunchedCompression = false;
            im.SetPlatformTextureSettings(s);
        }
    }
}
