import { SpecifyTool } from '../src/index';

describe('Specify Tool - Mock Mode', () => {
  let specifyTool: SpecifyTool;

  beforeEach(() => {
    // Ensure mock mode
    delete process.env.SPECIFY_API_TOKEN;
    specifyTool = new SpecifyTool();
  });

  test('should get taxonomy in mock mode', async () => {
    const taxonomy = await specifyTool.getTaxonomy('1');
    
    expect(taxonomy).toBeDefined();
    expect(taxonomy.id).toBe('1');
    expect(taxonomy.name).toBe('Utility Fog Taxonomy');
    expect(taxonomy.description).toBe('Mock taxonomy for development');
  });

  test('should create taxonomy in mock mode', async () => {
    const newTaxonomy = await specifyTool.createTaxonomy({
      name: 'Test Taxonomy',
      description: 'A test taxonomy'
    });

    expect(newTaxonomy).toBeDefined();
    expect(newTaxonomy.name).toBe('Test Taxonomy');
    expect(newTaxonomy.description).toBe('A test taxonomy');
    expect(newTaxonomy.id).toBeDefined();
    expect(newTaxonomy.created_at).toBeDefined();
  });

  test('should update taxonomy in mock mode', async () => {
    const updated = await specifyTool.updateTaxonomy('1', {
      description: 'Updated description'
    });

    expect(updated).toBeDefined();
    expect(updated.id).toBe('1');
    expect(updated.description).toBe('Updated description');
    expect(updated.updated_at).toBeDefined();
  });

  test('should handle not found error in mock mode', async () => {
    await expect(specifyTool.getTaxonomy('999')).rejects.toThrow('Taxonomy 999 not found');
  });
});
